#!/bin/bash
# Sentinel — Insider Threat Detection System
# Start script: Flask API (port 5000) + React dashboard (port 8000)

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   SENTINEL — Insider Threat Detection    ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# Check Python deps
echo "[1/4] Checking Python dependencies..."
python -c "import pandas,numpy,sklearn,flask,flask_cors,joblib,faker,pyarrow" 2>/dev/null || {
  echo "  Installing..."
  pip install pandas numpy scikit-learn scipy flask flask-cors python-dotenv joblib faker tqdm pyyaml pyarrow --break-system-packages -q
}
echo "  ✓ Python OK"

# Check data / train
echo "[2/4] Checking models..."
if [ ! -f "data/processed/scored_behaviors.parquet" ]; then
  echo "  No data found — running full training pipeline..."
  python scripts/generate_dataset.py --users 100 --days 180 --threats 8 --output data/raw
  python -c "
import sys; sys.path.insert(0,'.')
from src.pipeline.preprocessor import CERTPreprocessor
from src.pipeline.feature_engineer import FeatureEngineer
from src.models.isolation_forest_model import IsolationForestDetector
from src.models.autoencoder_model import AutoencoderDetector
from src.models.scorer import ScoringEngine
import numpy as np, pandas as pd
CERTPreprocessor().run()
X_all,X_train,meta=FeatureEngineer().run()
ifd=IsolationForestDetector(); ifd.train(X_train); if_s=ifd.predict_scores(X_all); ifd.save()
ae=AutoencoderDetector(); ae.train(X_train); ae_s=ae.predict_scores(X_all); ae.save()
eng=ScoringEngine(); scored=eng.score_all(meta,if_s,ae_s); ur=eng.aggregate_user_risk(scored); al=eng.generate_alerts(scored,ur); eng.save_results(scored,ur,al)
print('  Models trained.')
"
else
  echo "  ✓ Models ready"
fi

# Start Flask
echo "[3/4] Starting Flask API on http://localhost:5000 ..."
python src/api/app.py &
FLASK_PID=$!
sleep 2
curl -s http://localhost:5000/health > /dev/null 2>&1 && echo "  ✓ API running (PID $FLASK_PID)" || { echo "  ✗ API failed"; kill $FLASK_PID 2>/dev/null; exit 1; }

# Start React
echo "[4/4] Starting React dashboard on http://localhost:8000 ..."
cd frontend && npm run dev &
REACT_PID=$!
cd ..
sleep 2

echo ""
echo "  ════════════════════════════════════════════"
echo "  ✓  Dashboard  →  http://localhost:8000"
echo "  ✓  API        →  http://localhost:5000"
echo "  ════════════════════════════════════════════"
echo "  Press Ctrl+C to stop"
echo ""

trap "echo 'Stopping...'; kill $FLASK_PID $REACT_PID 2>/dev/null; exit 0" INT TERM
wait $FLASK_PID $REACT_PID
