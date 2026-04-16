"""
Master Training Pipeline
=========================
Runs the complete training workflow:
  1. Generate/load dataset
  2. Preprocess raw logs
  3. Engineer features
  4. Train Isolation Forest
  5. Train Autoencoder
  6. Score all users
  7. Generate alerts
  8. Save all artifacts

Usage:
    cd insider-threat-detection
    python scripts/train.py
    python scripts/train.py --generate-data --users 300 --days 365 --threats 15
"""

import os
import sys
import argparse
import logging
import numpy as np
import pandas as pd

# Ensure src is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline.preprocessor import CERTPreprocessor
from src.pipeline.feature_engineer import FeatureEngineer
from src.models.isolation_forest_model import IsolationForestDetector
from src.models.autoencoder_model import AutoencoderDetector
from src.models.scorer import ScoringEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/training.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def run_training(generate_data=False, n_users=100, n_days=365, n_threats=10):
    logger.info("=" * 70)
    logger.info("  INSIDER THREAT DETECTION — TRAINING PIPELINE")
    logger.info("=" * 70)

    # ----------------------------------------------------------------
    # STEP 1: Generate or validate data
    # ----------------------------------------------------------------
    if generate_data:
        logger.info("\n[STEP 1/7] Generating synthetic CERT-like dataset...")
        from scripts.generate_dataset import generate_all
        generate_all(n_users=n_users, n_days=n_days, n_threats=n_threats)
    else:
        raw_dir = "data/raw"
        required = ["logon.csv", "file.csv", "device.csv", "email.csv", "LDAP.csv"]
        missing = [f for f in required if not os.path.exists(os.path.join(raw_dir, f))]
        if missing:
            logger.warning(f"Missing files: {missing}")
            logger.info("Auto-generating synthetic data...")
            from scripts.generate_dataset import generate_all
            generate_all(n_users=n_users, n_days=n_days, n_threats=n_threats)
        else:
            logger.info("[STEP 1/7] Using existing raw data files.")

    # ----------------------------------------------------------------
    # STEP 2: Preprocess
    # ----------------------------------------------------------------
    logger.info("\n[STEP 2/7] Preprocessing raw logs...")
    preprocessor = CERTPreprocessor()
    features_df = preprocessor.run()

    # ----------------------------------------------------------------
    # STEP 3: Feature engineering
    # ----------------------------------------------------------------
    logger.info("\n[STEP 3/7] Engineering features...")
    fe = FeatureEngineer()
    X_all, X_train, meta_df = fe.run()

    logger.info(f"  X_train: {X_train.shape}, X_all: {X_all.shape}")

    # ----------------------------------------------------------------
    # STEP 4: Train Isolation Forest
    # ----------------------------------------------------------------
    logger.info("\n[STEP 4/7] Training Isolation Forest...")
    if_detector = IsolationForestDetector()
    if_detector.train(X_train)
    if_scores = if_detector.predict_scores(X_all)
    if_detector.save()
    logger.info(f"  IF score stats: mean={if_scores.mean():.1f}, "
                f"p90={np.percentile(if_scores, 90):.1f}, max={if_scores.max():.1f}")

    # ----------------------------------------------------------------
    # STEP 5: Train Autoencoder
    # ----------------------------------------------------------------
    logger.info("\n[STEP 5/7] Training Autoencoder...")
    ae_detector = AutoencoderDetector()
    ae_detector.train(X_train)
    ae_scores = ae_detector.predict_scores(X_all)
    ae_detector.save()
    logger.info(f"  AE score stats: mean={ae_scores.mean():.1f}, "
                f"p90={np.percentile(ae_scores, 90):.1f}, max={ae_scores.max():.1f}")

    # ----------------------------------------------------------------
    # STEP 6: Score all users
    # ----------------------------------------------------------------
    logger.info("\n[STEP 6/7] Scoring all users...")
    engine = ScoringEngine()
    scored_df = engine.score_all(meta_df, if_scores, ae_scores)
    user_risk_df = engine.aggregate_user_risk(scored_df)

    # ----------------------------------------------------------------
    # STEP 7: Generate alerts
    # ----------------------------------------------------------------
    logger.info("\n[STEP 7/7] Generating alerts...")
    alerts_df = engine.generate_alerts(scored_df, user_risk_df)
    summary = engine.save_results(scored_df, user_risk_df, alerts_df)

    # Evaluate against ground truth if available
    gt_path = "data/raw/ground_truth.csv"
    if os.path.exists(gt_path):
        gt_df = pd.read_csv(gt_path)
        logger.info("\n[EVALUATION] Checking against ground truth...")
        metrics = if_detector.evaluate(X_all, gt_df, meta_df)
        logger.info(f"  Metrics: {metrics}")

    # ----------------------------------------------------------------
    # Final summary
    # ----------------------------------------------------------------
    logger.info("\n" + "=" * 70)
    logger.info("  TRAINING COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Total users scored:   {summary['total_users']:>6,}")
    logger.info(f"  Total alerts:         {summary['total_alerts']:>6,}")
    logger.info(f"  CRITICAL alerts:      {summary['critical_alerts']:>6,}")
    logger.info(f"  HIGH alerts:          {summary['high_alerts']:>6,}")
    logger.info(f"  Risk distribution:    {summary['tier_distribution']}")
    logger.info(f"\n  Run the API with:  python src/api/app.py")
    logger.info("=" * 70)

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Insider Threat Detection Models")
    parser.add_argument("--generate-data", action="store_true",
                        help="Generate new synthetic dataset")
    parser.add_argument("--users",   type=int, default=100)
    parser.add_argument("--days",    type=int, default=365)
    parser.add_argument("--threats", type=int, default=10)
    args = parser.parse_args()

    run_training(
        generate_data=args.generate_data,
        n_users=args.users,
        n_days=args.days,
        n_threats=args.threats,
    )
