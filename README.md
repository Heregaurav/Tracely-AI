# Tracely AI — Insider Threat Detection System
### Enterprise-Grade UEBA Platform 

'''

████████╗██████╗  █████╗  ██████╗███████╗██╗     ██╗   ██╗     █████╗ ██╗
╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██╔════╝██║     ╚██╗ ██╔╝    ██╔══██╗██║
   ██║   ██████╔╝███████║██║     █████╗  ██║      ╚████╔╝     ███████║██║
   ██║   ██╔══██╗██╔══██║██║     ██╔══╝  ██║       ╚██╔╝      ██╔══██║██║
   ██║   ██║  ██║██║  ██║╚██████╗███████╗███████╗   ██║       ██║  ██║██║
   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚══════╝   ╚═╝       ╚═╝  ╚═╝╚═╝
'''
---

## Project Overview

Tracely AI is a production-grade User and Entity Behavior Analytics (UEBA) system that detects insider threats using unsupervised machine learning. It closely mirrors enterprise solutions deployed by IBM, Splunk, and Microsoft.

**Three insider threat archetypes detected:**
- **Data Exfiltrator** — Copies files to USB before resignation
- **Disgruntled Saboteur** — After-hours access to unauthorized systems
- **Negligent Insider** — Sends sensitive data externally

---

## Quick Start (Automated)

```bash
cd Tracely AI
bash start.sh
```

This automatically:
1. Installs Python dependencies
2. Generates the CERT-like dataset if not present
3. Trains both ML models
4. Starts Flask API on port 5000
5. Starts React dashboard on port 3000

Then open: **http://localhost:8000**

---

## Manual Setup (Step by Step)

### Prerequisites
- Python 3.10+
- Node.js 18+
- npm 9+

### Step 1 — Install Python dependencies
```bash
pip install pandas numpy scikit-learn scipy flask flask-cors python-dotenv joblib faker tqdm pyyaml
```

### Step 2 — Install React dependencies
```bash
cd frontend && npm install && cd ..
```

### Step 3 — Generate the CERT-like dataset
```bash
# Default: 100 users, 180 days, 8 insiders
python scripts/generate_dataset.py --users 100 --days 180 --threats 8

# For larger dataset (closer to real CERT r4.2 scale):
python scripts/generate_dataset.py --users 500 --days 365 --threats 20
```

This creates in `data/raw/`:
| File | Description |
|------|-------------|
| `LDAP.csv` | Employee directory (org structure) |
| `logon.csv` | Login/logoff events |
| `file.csv` | File access events |
| `device.csv` | USB device events |
| `email.csv` | Email send events |
| `ground_truth.csv` | Known insider labels for evaluation |

> **Using real CERT r4.2 data?** Download from https://resources.sei.cmu.edu/library/asset-view.cfm?assetid=508099 and place the 5 CSV files in `data/raw/`. The preprocessor handles both formats.

### Step 4 — Run the full training pipeline
```bash
python scripts/train.py
```

Or run each step manually:
```bash
# 4a. Preprocess raw logs → daily behavior matrix
python src/pipeline/preprocessor.py

# 4b. Feature engineering → ML-ready feature matrix
python src/pipeline/feature_engineer.py

# 4c. Train models + generate scores
python -c "
import sys, numpy as np, pandas as pd; sys.path.insert(0,'.')
from src.models.isolation_forest_model import IsolationForestDetector
from src.models.autoencoder_model import AutoencoderDetector
from src.models.scorer import ScoringEngine

X_all   = np.load('data/models/X_all.npy')
X_train = np.load('data/models/X_train.npy')
meta    = pd.read_parquet('data/models/X_meta.parquet')

ifd = IsolationForestDetector(); ifd.train(X_train)
if_scores = ifd.predict_scores(X_all); ifd.save()

ae = AutoencoderDetector(); ae.train(X_train)
ae_scores = ae.predict_scores(X_all); ae.save()

eng = ScoringEngine()
scored = eng.score_all(meta, if_scores, ae_scores)
ur     = eng.aggregate_user_risk(scored)
al     = eng.generate_alerts(scored, ur)
eng.save_results(scored, ur, al)
"
```

### Step 5 — Start Flask API
```bash
python src/api/app.py
# Running on http://localhost:5000
```

### Step 6 — Start React dashboard
```bash
cd frontend
npm run dev
# Running on http://localhost:8000
```

---

## Project Structure

```
Tracely AI/
│
├── config.yaml                    # All hyperparameters and paths
├── start.sh                       # One-command launcher
├── requirements.txt
│
├── data/
│   ├── raw/                       # CERT CSV files (generated or real)
│   ├── processed/                 # Parquet files (features, scores, alerts)
│   └── models/                    # Trained model artifacts
│
├── scripts/
│   ├── generate_dataset.py        # Synthetic CERT r4.2-like data generator
│   └── train.py                   # Master training pipeline
│
├── src/
│   ├── pipeline/
│   │   ├── preprocessor.py        # Raw log cleaning & aggregation
│   │   └── feature_engineer.py   # Feature selection, scaling, normalization
│   │
│   ├── models/
│   │   ├── isolation_forest_model.py  # Primary anomaly detector
│   │   ├── autoencoder_model.py       # Neural reconstruction model
│   │   └── scorer.py                  # Ensemble scoring + alert generation
│   │
│   └── api/
│       └── app.py                 # Flask REST API (7 endpoints)
│
├── frontend/                      # React + Vite application
│   └── src/
│       ├── App.jsx                # Shell with sidebar routing
│       ├── index.css              # Detective noir theme
│       ├── hooks/
│       │   └── useApi.js          # Data fetching with polling
│       ├── components/
│       │   └── shared.jsx         # TierBadge, ScoreRing, RiskBar, etc.
│       └── pages/
│           ├── Overview.jsx       # Dashboard: stats, timeline, alerts
│           ├── Threats.jsx        # Alert table with filters & export
│           ├── Users.jsx          # User watchlist (grid + table view)
│           ├── UserModal.jsx      # Deep-dive user dossier
│           ├── Heatmap.jsx        # Dept × weekday risk grid
│           ├── Timeline.jsx       # 7/30/90 day rolling chart
│           ├── Departments.jsx    # Org-level risk breakdown + radar
│           └── Reports.jsx        # Model info, exports, retrain control
│
├── logs/
└── reports/                       # JSON threat reports (timestamped)
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | System health check |
| GET | `/api/stats` | Summary: user counts, alert counts, tier distribution |
| GET | `/api/threats?tier=HIGH&page=1` | Paginated alert list |
| GET | `/api/users?sort=max_risk_score&tier=HIGH` | User watchlist |
| GET | `/api/users/:user_id` | Full user dossier with history |
| GET | `/api/timeline?days=30` | Daily risk score time series |
| GET | `/api/heatmap` | Dept × weekday risk averages |
| GET | `/api/departments` | Per-department risk aggregates |
| POST | `/api/retrain` | Trigger background model retraining |

---

## Machine Learning Architecture

### Feature Engineering (27 features)
| Category | Features |
|----------|----------|
| Login behavior | `login_count`, `login_hour_mean`, `login_hour_std`, `after_hours_logins`, `after_hours_ratio`, `unique_pcs` |
| Sessions | `session_duration_total`, `session_count` |
| File access | `files_accessed`, `files_after_hours`, `sensitive_files`, `files_per_session` |
| USB/Device | `usb_count`, `usb_after_hours` |
| Email | `emails_sent`, `emails_external`, `email_attachments` |
| Temporal | `day_of_week`, `is_weekend` |
| **Rolling deviations** | `files_accessed_deviation`, `usb_count_deviation`, `emails_external_deviation`, `after_hours_ratio_deviation`, `sensitive_files_deviation`, `email_attachments_deviation`, `session_duration_total_deviation` |

Rolling deviation features compare each day's activity to the user's own 7-day baseline — the most powerful signal for insider threat detection.

### Models
| Model | Type | Role |
|-------|------|------|
| Isolation Forest | Unsupervised | Primary detector. Isolates anomalies via random partitioning. Weight: 60% |
| Autoencoder (PCA fallback) | Neural / Unsupervised | Reconstruction error detector. Weight: 40% |

### Risk Tiers
| Tier | Score | Action |
|------|-------|--------|
| CRITICAL | >95 | Immediate investigation |
| HIGH | 85–95 | Escalate to security team |
| MEDIUM | 70–85 | Review within 48h |
| LOW | 40–70 | Monitor, flag for weekly review |
| NORMAL | <40 | Baseline behavior |

---

## Dashboard Features

| Page | Features |
|------|---------|
| **Overview** | Stat cards, 60-day area chart, live alert feed, dept risk bar chart, tier distribution |
| **Active Threats** | Sortable alert table, tier filters, user search, CSV export, detail modal |
| **User Profiles** | Card grid + table toggle, risk score bars, trend indicators, click-through dossier |
| **User Dossier** | Score ring, 30-day history chart, behavior breakdown bars, alert history |
| **Risk Heatmap** | Dept × weekday intensity grid, hover tooltips, top-risk combos |
| **Timeline** | 7/30/60/90-day chart, incident calendar, threshold reference lines |
| **Departments** | Bar chart, radar chart, full department table |
| **Reports** | Model config, live snapshot, CSV/JSON exports, retrain trigger |

---



## References

1. CERT Insider Threat Dataset — Carnegie Mellon University SEI
2. Liu, F.T., et al. — "Isolation Forest" (ICDM 2008)
3. Chandola et al. — "Anomaly Detection: A Survey" (ACM 2009)
4. Scikit-learn Documentation — sklearn.ensemble.IsolationForest
5. UEBA in Enterprise Security — Gartner, Splunk, IBM QRadar
