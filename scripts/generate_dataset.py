"""
CERT Insider Threat Dataset Generator
=====================================
Generates statistically realistic synthetic data matching CERT r4.2 schema.
Produces 5 CSV files: logon, file, device, email, LDAP
Includes ground-truth labels: 3 insider threat archetypes injected.

Usage:
    python scripts/generate_dataset.py --users 500 --days 365 --threats 15
"""

import pandas as pd
import numpy as np
import random
import os
import argparse
import yaml
from datetime import datetime, timedelta
from faker import Faker
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

fake = Faker()
rng = np.random.default_rng(42)
random.seed(42)


# ---------------------------------------------------------------------------
# Organisation structure
# ---------------------------------------------------------------------------
DEPARTMENTS = {
    "IT":           {"size": 0.12, "pc_prefix": "PC-IT",    "server_access": True},
    "Finance":      {"size": 0.10, "pc_prefix": "PC-FIN",   "server_access": True},
    "HR":           {"size": 0.08, "pc_prefix": "PC-HR",    "server_access": False},
    "Engineering":  {"size": 0.20, "pc_prefix": "PC-ENG",   "server_access": True},
    "Sales":        {"size": 0.18, "pc_prefix": "PC-SAL",   "server_access": False},
    "Marketing":    {"size": 0.10, "pc_prefix": "PC-MKT",   "server_access": False},
    "Legal":        {"size": 0.07, "pc_prefix": "PC-LEG",   "server_access": True},
    "Operations":   {"size": 0.15, "pc_prefix": "PC-OPS",   "server_access": False},
}

ROLES = ["Manager", "Senior Analyst", "Analyst", "Associate", "Director", "VP", "Intern"]
SENSITIVE_FOLDERS = [
    "/finance/confidential/", "/hr/salaries/", "/legal/contracts/",
    "/engineering/source_code/", "/executive/strategy/", "/it/credentials/",
]
EMAIL_DOMAINS_INTERNAL = ["dtaa.com"]   # CERT dataset uses this domain
EMAIL_DOMAINS_EXTERNAL = [
    "gmail.com", "yahoo.com", "hotmail.com", "protonmail.com",
    "outlook.com", "competitor.com", "recruiter.io"
]

# ---------------------------------------------------------------------------
# Insider threat archetypes (injected as ground truth)
# ---------------------------------------------------------------------------
THREAT_ARCHETYPES = {
    "data_exfiltrator": {
        "description": "Employee copying files to USB before leaving",
        "trigger_week": -8,   # starts N weeks before end
        "behaviors": {
            "usb_multiplier": 12.0,
            "after_hours_prob": 0.7,
            "files_multiplier": 8.0,
            "sensitive_access_multiplier": 5.0,
        }
    },
    "disgruntled_saboteur": {
        "description": "Employee accessing systems they shouldn't",
        "trigger_week": -12,
        "behaviors": {
            "after_hours_prob": 0.8,
            "cross_dept_access": True,
            "login_hour_shift": 3,   # logs in at unusual hours
            "email_external_multiplier": 4.0,
        }
    },
    "negligent_insider": {
        "description": "Accidental data leaker - sends sensitive data externally",
        "trigger_week": -4,
        "behaviors": {
            "email_attachment_multiplier": 6.0,
            "email_external_multiplier": 3.0,
            "usb_multiplier": 2.0,
        }
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def workday_timestamps(date, n, dept, is_threat=False, threat_type=None):
    """Generate n timestamps for a given day. Normal = business hours. Threats = shifted."""
    timestamps = []
    for _ in range(n):
        if is_threat and threat_type in ("data_exfiltrator", "disgruntled_saboteur"):
            # Prefer late night / early morning
            hour = rng.choice([22, 23, 0, 1, 2, 3, 19, 20, 21])
        else:
            # Normal: 8am-6pm, slightly Gaussian around 10am
            hour = int(np.clip(rng.normal(10, 2.5), 7, 19))
        minute = rng.integers(0, 60)
        second = rng.integers(0, 60)
        ts = datetime(date.year, date.month, date.day, hour, minute, second)
        timestamps.append(ts)
    return sorted(timestamps)


def format_ts(dt):
    return dt.strftime("%m/%d/%Y %H:%M:%S")


# ---------------------------------------------------------------------------
# Generate LDAP (org chart)
# ---------------------------------------------------------------------------
def generate_ldap(n_users):
    logger.info(f"Generating LDAP for {n_users} users...")
    records = []
    user_id = 1
    for dept, info in DEPARTMENTS.items():
        n_dept = max(2, int(n_users * info["size"]))
        for i in range(n_dept):
            uid = f"CER{user_id:04d}"
            records.append({
                "user_id": uid,
                "name": fake.name(),
                "email": f"{uid.lower()}@dtaa.com",
                "department": dept,
                "role": rng.choice(ROLES),
                "team": f"{dept}-Team{(i // 5) + 1}",
                "supervisor": None,
                "start_date": fake.date_between(start_date="-5y", end_date="-6m"),
                "pc": f"{info['pc_prefix']}-{rng.integers(100, 999)}",
            })
            user_id += 1
            if user_id > n_users:
                break
        if user_id > n_users:
            break
    df = pd.DataFrame(records)
    # assign supervisors
    for dept in df["department"].unique():
        dept_idx = df[df["department"] == dept].index.tolist()
        if len(dept_idx) > 1:
            supervisor_uid = df.loc[dept_idx[0], "user_id"]
            for idx in dept_idx[1:]:
                df.at[idx, "supervisor"] = supervisor_uid
    return df


# ---------------------------------------------------------------------------
# Generate logon events
# ---------------------------------------------------------------------------
def generate_logon(ldap_df, date_range, threat_users):
    logger.info("Generating logon events...")
    records = []
    users = ldap_df["user_id"].tolist()
    pc_map = dict(zip(ldap_df["user_id"], ldap_df["pc"]))
    dept_map = dict(zip(ldap_df["user_id"], ldap_df["department"]))
    total_days = len(date_range)

    for user in tqdm(users, desc="Logon"):
        dept = dept_map[user]
        is_threat = user in threat_users
        threat_type = threat_users.get(user, {}).get("type") if is_threat else None
        trigger_date = threat_users.get(user, {}).get("trigger_date") if is_threat else None

        for date in date_range:
            # Skip weekends 85% of the time
            if date.weekday() >= 5 and rng.random() > 0.15:
                continue
            # Absence (vacation/sick) ~5%
            if rng.random() < 0.05:
                continue

            active_threat = is_threat and trigger_date and date >= trigger_date

            n_sessions = int(rng.normal(2.5, 0.8))
            n_sessions = max(1, n_sessions)
            if active_threat and threat_type == "disgruntled_saboteur":
                n_sessions = int(n_sessions * 1.5)

            for _ in range(n_sessions):
                if active_threat and threat_type == "disgruntled_saboteur":
                    hour = int(rng.choice([22, 23, 0, 1, 17, 18, 19, 20]))
                else:
                    hour = int(np.clip(rng.normal(9, 2), 7, 19))
                minute = rng.integers(0, 60)
                ts = datetime(date.year, date.month, date.day, hour, minute, rng.integers(0, 60))

                # Sometimes use a different PC (suspicious if across dept)
                if active_threat and rng.random() < 0.3:
                    other_dept = rng.choice([d for d in DEPARTMENTS if d != dept])
                    prefix = DEPARTMENTS[other_dept]["pc_prefix"]
                    pc = f"{prefix}-{rng.integers(100, 999)}"
                else:
                    pc = pc_map[user]

                activity = rng.choice(["Logon", "Logoff"], p=[0.5, 0.5])
                records.append({
                    "id": f"L{len(records)+1:08d}",
                    "date": format_ts(ts),
                    "user": user,
                    "pc": pc,
                    "activity": activity,
                })

    df = pd.DataFrame(records)
    logger.info(f"Logon records: {len(df):,}")
    return df


# ---------------------------------------------------------------------------
# Generate file access events
# ---------------------------------------------------------------------------
def generate_file(ldap_df, date_range, threat_users):
    logger.info("Generating file access events...")
    records = []
    dept_map = dict(zip(ldap_df["user_id"], ldap_df["department"]))
    pc_map = dict(zip(ldap_df["user_id"], ldap_df["pc"]))

    FILE_EXTENSIONS = [".docx", ".xlsx", ".pdf", ".pptx", ".txt", ".csv", ".zip", ".exe", ".py", ".sql"]
    ACTIVITIES = ["Open", "Copy", "Write", "Delete", "Read"]

    for user in tqdm(ldap_df["user_id"].tolist(), desc="Files"):
        dept = dept_map[user]
        is_threat = user in threat_users
        threat_type = threat_users.get(user, {}).get("type") if is_threat else None
        trigger_date = threat_users.get(user, {}).get("trigger_date") if is_threat else None

        for date in date_range:
            if date.weekday() >= 5 and rng.random() > 0.1:
                continue
            if rng.random() < 0.08:
                continue

            active_threat = is_threat and trigger_date and date >= trigger_date
            behavior = THREAT_ARCHETYPES.get(threat_type, {}).get("behaviors", {}) if active_threat else {}

            base_files = int(rng.normal(8, 4))
            base_files = max(0, base_files)
            multiplier = behavior.get("files_multiplier", 1.0)
            n_files = int(base_files * multiplier)

            for _ in range(n_files):
                # Folder selection
                if active_threat and "sensitive_access_multiplier" in behavior and rng.random() < 0.4:
                    folder = rng.choice(SENSITIVE_FOLDERS)
                    filename = f"confidential_{fake.word()}{rng.choice(FILE_EXTENSIONS)}"
                else:
                    folder = f"/{dept.lower()}/documents/{'work' if rng.random() > 0.2 else 'personal'}/"
                    filename = f"{fake.word()}_{fake.word()}{rng.choice(FILE_EXTENSIONS)}"

                after_hours_prob = behavior.get("after_hours_prob", 0.1)
                if rng.random() < after_hours_prob:
                    hour = int(rng.choice([20, 21, 22, 23, 6, 7]))
                else:
                    hour = int(np.clip(rng.normal(11, 2.5), 7, 18))

                ts = datetime(date.year, date.month, date.day, hour, rng.integers(0, 60), rng.integers(0, 60))

                activity = rng.choice(ACTIVITIES, p=[0.45, 0.2, 0.15, 0.05, 0.15])
                if active_threat and threat_type == "data_exfiltrator":
                    activity = rng.choice(["Copy", "Read"], p=[0.6, 0.4])

                records.append({
                    "id": f"F{len(records)+1:08d}",
                    "date": format_ts(ts),
                    "user": user,
                    "pc": pc_map[user],
                    "filename": folder + filename,
                    "activity": activity,
                })

    df = pd.DataFrame(records)
    logger.info(f"File records: {len(df):,}")
    return df


# ---------------------------------------------------------------------------
# Generate device (USB) events
# ---------------------------------------------------------------------------
def generate_device(ldap_df, date_range, threat_users):
    logger.info("Generating device events...")
    records = []
    pc_map = dict(zip(ldap_df["user_id"], ldap_df["pc"]))

    for user in tqdm(ldap_df["user_id"].tolist(), desc="Device"):
        is_threat = user in threat_users
        threat_type = threat_users.get(user, {}).get("type") if is_threat else None
        trigger_date = threat_users.get(user, {}).get("trigger_date") if is_threat else None

        for date in date_range:
            if date.weekday() >= 5:
                continue

            active_threat = is_threat and trigger_date and date >= trigger_date
            behavior = THREAT_ARCHETYPES.get(threat_type, {}).get("behaviors", {}) if active_threat else {}

            # Base USB probability: ~8% of days for normal user
            base_prob = 0.08
            multiplier = behavior.get("usb_multiplier", 1.0)
            effective_prob = min(0.95, base_prob * multiplier)

            if rng.random() > effective_prob:
                continue

            n_events = int(rng.choice([1, 2, 3], p=[0.6, 0.3, 0.1]))
            if active_threat:
                n_events = max(n_events, int(rng.normal(3, 1)))

            after_prob = behavior.get("after_hours_prob", 0.05)
            if rng.random() < after_prob:
                hour = int(rng.choice([19, 20, 21, 22, 23]))
            else:
                hour = int(np.clip(rng.normal(11, 2), 8, 17))

            ts = datetime(date.year, date.month, date.day, hour, rng.integers(0, 60), rng.integers(0, 60))

            records.append({
                "id": f"D{len(records)+1:08d}",
                "date": format_ts(ts),
                "user": user,
                "pc": pc_map[user],
                "activity": rng.choice(["Connect", "Disconnect"], p=[0.5, 0.5]),
            })

    df = pd.DataFrame(records)
    logger.info(f"Device records: {len(df):,}")
    return df


# ---------------------------------------------------------------------------
# Generate email events
# ---------------------------------------------------------------------------
def generate_email(ldap_df, date_range, threat_users):
    logger.info("Generating email events...")
    records = []
    email_map = dict(zip(ldap_df["user_id"], ldap_df["email"]))

    EMAIL_SUBJECTS_NORMAL = [
        "Re: Weekly sync", "FW: Budget review", "Meeting tomorrow",
        "Project update", "Quick question", "Documentation",
    ]
    EMAIL_SUBJECTS_THREAT = [
        "Personal files", "Resume", "Job opportunity",
        "Confidential", "FW: Salary data", "Strategic plans",
    ]

    for user in tqdm(ldap_df["user_id"].tolist(), desc="Email"):
        is_threat = user in threat_users
        threat_type = threat_users.get(user, {}).get("type") if is_threat else None
        trigger_date = threat_users.get(user, {}).get("trigger_date") if is_threat else None

        for date in date_range:
            if date.weekday() >= 5 and rng.random() > 0.05:
                continue
            if rng.random() < 0.05:
                continue

            active_threat = is_threat and trigger_date and date >= trigger_date
            behavior = THREAT_ARCHETYPES.get(threat_type, {}).get("behaviors", {}) if active_threat else {}

            base_emails = int(rng.normal(12, 5))
            base_emails = max(0, base_emails)
            n_emails = int(base_emails * behavior.get("email_external_multiplier", 1.0))
            n_emails = max(base_emails, n_emails)

            for _ in range(n_emails):
                hour = int(np.clip(rng.normal(11, 2), 7, 18))
                ts = datetime(date.year, date.month, date.day, hour, rng.integers(0, 60), rng.integers(0, 60))

                # Recipient
                ext_prob = 0.05
                if active_threat:
                    ext_prob = min(0.7, 0.05 * behavior.get("email_external_multiplier", 1.0))

                if rng.random() < ext_prob:
                    to_domain = rng.choice(EMAIL_DOMAINS_EXTERNAL)
                    to_user = fake.user_name()
                    to_email = f"{to_user}@{to_domain}"
                else:
                    # Internal recipient
                    other = rng.choice(ldap_df["user_id"].tolist())
                    to_email = email_map.get(other, f"unknown@dtaa.com")

                attachments = 0
                att_mult = behavior.get("email_attachment_multiplier", 1.0)
                if rng.random() < min(0.9, 0.15 * att_mult):
                    attachments = int(rng.choice([1, 2, 3], p=[0.6, 0.3, 0.1]) * att_mult)
                    attachments = min(attachments, 10)

                if active_threat:
                    subject = rng.choice(EMAIL_SUBJECTS_THREAT)
                else:
                    subject = rng.choice(EMAIL_SUBJECTS_NORMAL)

                records.append({
                    "id": f"E{len(records)+1:08d}",
                    "date": format_ts(ts),
                    "user": user,
                    "pc": f"PC-{rng.integers(100, 999)}",
                    "to": to_email,
                    "from": email_map[user],
                    "activity": "Send",
                    "attachments": attachments,
                    "size": int(rng.normal(50000, 30000) * (attachments + 1)),
                    "content": subject,
                })

    df = pd.DataFrame(records)
    logger.info(f"Email records: {len(df):,}")
    return df


# ---------------------------------------------------------------------------
# Inject insider threats & generate ground truth labels
# ---------------------------------------------------------------------------
def assign_threats(ldap_df, date_range, n_threats):
    """Randomly assign threat archetypes to users and compute trigger dates."""
    users = ldap_df["user_id"].tolist()
    threat_users_list = rng.choice(users, size=min(n_threats, len(users)), replace=False)

    archetypes = list(THREAT_ARCHETYPES.keys())
    last_date = date_range[-1]
    threat_users = {}
    ground_truth = []

    for i, uid in enumerate(threat_users_list):
        archetype = archetypes[i % len(archetypes)]
        trigger_weeks = THREAT_ARCHETYPES[archetype]["trigger_week"]
        trigger_date = last_date + timedelta(weeks=trigger_weeks)
        trigger_date = max(date_range[0], trigger_date)

        threat_users[uid] = {
            "type": archetype,
            "trigger_date": trigger_date,
        }
        ground_truth.append({
            "user_id": uid,
            "threat_type": archetype,
            "trigger_date": trigger_date.strftime("%Y-%m-%d"),
            "is_insider": True,
            "description": THREAT_ARCHETYPES[archetype]["description"],
        })

    # Add normal users
    for uid in users:
        if uid not in threat_users:
            ground_truth.append({
                "user_id": uid,
                "threat_type": "none",
                "trigger_date": None,
                "is_insider": False,
                "description": "Normal behavior",
            })

    return threat_users, pd.DataFrame(ground_truth)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def generate_all(n_users=200, n_days=365, n_threats=10, output_dir="data/raw"):
    os.makedirs(output_dir, exist_ok=True)

    # Date range (business-adjacent: include some weekends)
    start = datetime(2010, 1, 4)
    date_range = [start + timedelta(days=i) for i in range(n_days)]

    logger.info(f"Generating CERT-like dataset: {n_users} users, {n_days} days, {n_threats} insiders")

    # 1. LDAP
    ldap_df = generate_ldap(n_users)
    ldap_df.to_csv(os.path.join(output_dir, "LDAP.csv"), index=False)
    logger.info(f"LDAP saved: {len(ldap_df)} users")

    # 2. Assign threats
    threat_users, ground_truth_df = assign_threats(ldap_df, date_range, n_threats)
    ground_truth_df.to_csv(os.path.join(output_dir, "ground_truth.csv"), index=False)
    threat_uids = set(threat_users.keys())
    logger.info(f"Insider threats: {len(threat_uids)} users ({', '.join(list(threat_uids)[:5])}...)")

    # 3. Generate all logs
    logon_df = generate_logon(ldap_df, date_range, threat_users)
    logon_df.to_csv(os.path.join(output_dir, "logon.csv"), index=False)

    file_df = generate_file(ldap_df, date_range, threat_users)
    file_df.to_csv(os.path.join(output_dir, "file.csv"), index=False)

    device_df = generate_device(ldap_df, date_range, threat_users)
    device_df.to_csv(os.path.join(output_dir, "device.csv"), index=False)

    email_df = generate_email(ldap_df, date_range, threat_users)
    email_df.to_csv(os.path.join(output_dir, "email.csv"), index=False)

    # Summary
    print("\n" + "="*60)
    print("  CERT-LIKE DATASET GENERATION COMPLETE")
    print("="*60)
    print(f"  Users:          {len(ldap_df):>8,}")
    print(f"  Insider threats:{len(threat_uids):>8,}")
    print(f"  Logon events:   {len(logon_df):>8,}")
    print(f"  File events:    {len(file_df):>8,}")
    print(f"  Device events:  {len(device_df):>8,}")
    print(f"  Email events:   {len(email_df):>8,}")
    print(f"  Date range:     {date_range[0].date()} → {date_range[-1].date()}")
    print(f"  Output:         {output_dir}/")
    print("="*60 + "\n")

    return {
        "ldap": ldap_df,
        "logon": logon_df,
        "file": file_df,
        "device": device_df,
        "email": email_df,
        "ground_truth": ground_truth_df,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate CERT-like Insider Threat Dataset")
    parser.add_argument("--users",   type=int, default=200,  help="Number of employees")
    parser.add_argument("--days",    type=int, default=365,  help="Simulation days")
    parser.add_argument("--threats", type=int, default=10,   help="Number of insider threats")
    parser.add_argument("--output",  type=str, default="data/raw", help="Output directory")
    args = parser.parse_args()

    generate_all(
        n_users=args.users,
        n_days=args.days,
        n_threats=args.threats,
        output_dir=args.output,
    )
