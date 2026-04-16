"""
Autoencoder Anomaly Detection Model
======================================
Neural network that learns to compress & reconstruct normal behavior.
High reconstruction error = anomalous behavior.

Architecture: Input → Encoder → Bottleneck → Decoder → Reconstruction
Trained ONLY on normal behavior. Anomalies reconstruct poorly.
"""

import numpy as np
import os
import yaml
import joblib
import logging
import json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Try importing TensorFlow gracefully
try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers, Model, callbacks
    TF_AVAILABLE = True
    tf.get_logger().setLevel("ERROR")
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
except ImportError:
    TF_AVAILABLE = False
    logger.warning("TensorFlow not available. Autoencoder will run in sklearn fallback mode.")


class AutoencoderDetector:
    """
    Deep Autoencoder for anomaly detection.
    Falls back to PCA-based reconstruction if TF unavailable.
    """

    def __init__(self, config_path="config.yaml"):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)
        self.ae_cfg = self.cfg["models"]["autoencoder"]
        self.model_dir = self.cfg["paths"]["models"]
        os.makedirs(self.model_dir, exist_ok=True)
        self.model = None
        self.threshold = None  # reconstruction error threshold for anomaly
        self.score_min = None
        self.score_max = None
        self.input_dim = None

    # ------------------------------------------------------------------
    # TensorFlow Autoencoder
    # ------------------------------------------------------------------
    def _build_keras_model(self, input_dim):
        """Build encoder-bottleneck-decoder architecture."""
        enc_layers = self.ae_cfg["encoding_layers"]
        dec_layers = self.ae_cfg["decoding_layers"]
        dropout = self.ae_cfg["dropout_rate"]

        inp = keras.Input(shape=(input_dim,), name="input")
        x = inp

        # Encoder
        for i, units in enumerate(enc_layers):
            x = layers.Dense(units, activation=self.ae_cfg["activation"],
                             name=f"enc_{i}")(x)
            x = layers.BatchNormalization()(x)
            if dropout > 0:
                x = layers.Dropout(dropout)(x)

        # Bottleneck (smallest representation)
        bottleneck = x
        bottleneck_dim = enc_layers[-1]

        # Decoder (mirror of encoder)
        for i, units in enumerate(dec_layers):
            x = layers.Dense(units, activation=self.ae_cfg["activation"],
                             name=f"dec_{i}")(x)
            x = layers.BatchNormalization()(x)

        # Reconstruction output
        output = layers.Dense(input_dim, activation="linear", name="reconstruction")(x)

        model = Model(inp, output, name="autoencoder")
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=self.ae_cfg["learning_rate"]),
            loss="mse",
            metrics=["mae"],
        )
        self.input_dim = input_dim
        return model

    def _build_sklearn_fallback(self, input_dim):
        """PCA-based reconstruction fallback when TF is unavailable."""
        from sklearn.decomposition import PCA
        n_components = min(8, input_dim // 2)
        return PCA(n_components=n_components, random_state=42)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def train(self, X_train, X_val=None):
        """
        Train autoencoder on normal behavior.
        Target = input (reconstruction task).
        """
        input_dim = X_train.shape[1]
        logger.info(f"Training Autoencoder: {input_dim} → {self.ae_cfg['encoding_layers']} → {input_dim}")

        if TF_AVAILABLE:
            self.model = self._build_keras_model(input_dim)
            self.model.summary(print_fn=lambda x: logger.debug(x))

            cb = [
                callbacks.EarlyStopping(
                    monitor="val_loss", patience=8,
                    restore_best_weights=True, verbose=0
                ),
                callbacks.ReduceLROnPlateau(
                    monitor="val_loss", factor=0.5, patience=5, verbose=0
                ),
            ]

            history = self.model.fit(
                X_train, X_train,
                epochs=self.ae_cfg["epochs"],
                batch_size=self.ae_cfg["batch_size"],
                validation_split=self.ae_cfg["validation_split"] if X_val is None else 0.0,
                validation_data=(X_val, X_val) if X_val is not None else None,
                callbacks=cb,
                verbose=0,
            )

            final_loss = history.history["val_loss"][-1]
            logger.info(f"Training complete. Final val_loss: {final_loss:.6f}")
            logger.info(f"Trained for {len(history.history['loss'])} epochs")

        else:
            # PCA fallback
            logger.info("Using PCA fallback for autoencoder.")
            self.model = self._build_sklearn_fallback(input_dim)
            self.model.fit(X_train)

        # Compute reconstruction errors on training set to set threshold
        rec_errors = self._reconstruction_error(X_train)
        self.threshold = float(np.percentile(rec_errors, 95))
        self.score_min = float(rec_errors.min())
        self.score_max = float(np.percentile(rec_errors, 99.9))  # cap at 99.9th for robustness

        logger.info(f"Anomaly threshold (95th percentile): {self.threshold:.4f}")
        return self

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def _reconstruction_error(self, X):
        """Compute mean squared reconstruction error per sample."""
        if TF_AVAILABLE and isinstance(self.model, Model):
            X_reconstructed = self.model.predict(X, verbose=0)
        else:
            # PCA: project + inverse_project
            X_proj = self.model.transform(X)
            X_reconstructed = self.model.inverse_transform(X_proj)

        mse = np.mean((X - X_reconstructed) ** 2, axis=1)
        return mse

    def predict_scores(self, X):
        """
        Return normalized anomaly scores [0, 100].
        Higher = more anomalous.
        """
        errors = self._reconstruction_error(X)
        normalized = (errors - self.score_min) / (self.score_max - self.score_min + 1e-10)
        return np.clip(normalized * 100, 0, 100)

    def predict_labels(self, X):
        """Return 1 (anomaly) or 0 (normal) based on threshold."""
        errors = self._reconstruction_error(X)
        return (errors > self.threshold).astype(int)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self, suffix=""):
        if TF_AVAILABLE and isinstance(self.model, Model):
            model_path = os.path.join(self.model_dir, f"autoencoder{suffix}.keras")
            self.model.save(model_path)
        else:
            model_path = os.path.join(self.model_dir, f"autoencoder_pca{suffix}.pkl")
            joblib.dump(self.model, model_path)

        meta_path = os.path.join(self.model_dir, f"autoencoder_meta{suffix}.json")
        meta = {
            "threshold": self.threshold,
            "score_min": self.score_min,
            "score_max": self.score_max,
            "input_dim": self.input_dim,
            "tf_available": TF_AVAILABLE,
            "model_path": model_path,
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        logger.info(f"Autoencoder saved → {model_path}")
        return model_path

    def load(self, suffix=""):
        meta_path = os.path.join(self.model_dir, f"autoencoder_meta{suffix}.json")
        with open(meta_path) as f:
            meta = json.load(f)

        self.threshold = meta["threshold"]
        self.score_min = meta["score_min"]
        self.score_max = meta["score_max"]
        self.input_dim = meta["input_dim"]

        if meta.get("tf_available") and TF_AVAILABLE:
            self.model = keras.models.load_model(meta["model_path"])
        else:
            self.model = joblib.load(meta["model_path"])
        logger.info(f"Autoencoder loaded ← {meta['model_path']}")
        return self


if __name__ == "__main__":
    X_train = np.load("data/models/X_train.npy")
    X_all = np.load("data/models/X_all.npy")

    ae = AutoencoderDetector()
    ae.train(X_train)
    scores = ae.predict_scores(X_all)
    print(f"AE Score distribution: min={scores.min():.1f}, mean={scores.mean():.1f}, max={scores.max():.1f}")
    ae.save()
