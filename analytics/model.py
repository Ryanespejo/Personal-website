"""ML model training, serialisation, and pure-Python prediction.

Training uses scikit-learn (only needed locally / in CI).
Prediction uses only stdlib math — safe for serverless cold-starts.
"""

import json
import math
import os
import time

from . import config


# ── Pure-Python inference (no numpy / sklearn) ──────────────────────────────

def sigmoid(z: float) -> float:
    """Numerically-stable sigmoid."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def predict(model_data: dict, features: dict) -> dict:
    """Apply the trained logistic-regression model.

    Works with plain Python — designed for Vercel serverless.
    """
    names  = model_data["features"]
    coefs  = model_data["coefficients"]
    bias   = model_data["intercept"]
    means  = model_data["scaler"]["mean"]
    scales = model_data["scaler"]["scale"]

    z = bias
    contributions: list[tuple[str, float, float]] = []

    for i, name in enumerate(names):
        raw = features.get(name, 0.0)
        scaled = (raw - means[i]) / scales[i] if scales[i] != 0 else 0.0
        c = coefs[i] * scaled
        z += c
        contributions.append((name, abs(c), c))

    prob = sigmoid(z)
    confidence = abs(prob - 0.5) * 2.0

    contributions.sort(key=lambda x: x[1], reverse=True)
    key_factors = [
        {
            "feature": name,
            "label": _FEATURE_LABELS.get(name, name),
            "impact": round(mag, 3),
            "direction": "favors_p1" if direction > 0 else "favors_p2",
        }
        for name, mag, direction in contributions[:5]
    ]

    return {
        "p1_win_prob": round(prob, 4),
        "p2_win_prob": round(1 - prob, 4),
        "confidence": round(confidence, 4),
        "key_factors": key_factors,
    }


_FEATURE_LABELS = {
    "rank_diff":              "Ranking difference",
    "rank_ratio":             "Ranking closeness",
    "points_diff":            "Rating-points gap",
    "points_ratio":           "Rating-points ratio",
    "age_diff":               "Age difference",
    "height_diff":            "Height difference",
    "h2h_ratio":              "Head-to-head record",
    "p1_win_rate_52w":        "52-week win rate (P1)",
    "p2_win_rate_52w":        "52-week win rate (P2)",
    "p1_surface_win_rate":    "Surface win rate (P1)",
    "p2_surface_win_rate":    "Surface win rate (P2)",
    "p1_ace_rate":            "Ace rate (P1)",
    "p2_ace_rate":            "Ace rate (P2)",
    "p1_bp_save_rate":        "Break-point save % (P1)",
    "p2_bp_save_rate":        "Break-point save % (P2)",
    "p1_first_serve_win_pct": "1st-serve win % (P1)",
    "p2_first_serve_win_pct": "1st-serve win % (P2)",
    "surface_clay":           "Clay court",
    "surface_grass":          "Grass court",
    "surface_hard":           "Hard court",
    "surface_carpet":         "Carpet court",
    "best_of_5":              "Best-of-5 format",
}


# ── Training (requires numpy + scikit-learn) ─────────────────────────────────

def train(features_list: list[dict], targets: list[int]) -> dict:
    """Train a logistic-regression model and return a JSON-serialisable dict."""
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        raise ImportError("Training requires: pip install numpy scikit-learn")

    feature_names = config.FEATURES

    X = np.array(
        [[f.get(name, 0.0) for name in feature_names] for f in features_list],
        dtype=np.float64,
    )
    y = np.array(targets, dtype=np.int64)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # Chronological split — last 20 % for testing
    split = int(len(X) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    model = LogisticRegression(max_iter=1000, C=1.0, solver="lbfgs", random_state=42)
    model.fit(X_train_s, y_train)

    y_pred = model.predict(X_test_s)
    y_prob = model.predict_proba(X_test_s)[:, 1]

    acc = accuracy_score(y_test, y_pred)
    auc = roc_auc_score(y_test, y_prob)
    ll  = log_loss(y_test, y_prob)

    coef_abs = np.abs(model.coef_[0])
    order = np.argsort(coef_abs)[::-1]
    top_features = [
        {"name": feature_names[i], "importance": round(float(coef_abs[i]), 4)}
        for i in order[:10]
    ]

    return {
        "model_type": "logistic_regression",
        "features": feature_names,
        "coefficients": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "scaler": {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
        },
        "metadata": {
            "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "training_samples": int(len(X_train)),
            "test_samples": int(len(X_test)),
            "accuracy": round(float(acc), 4),
            "auc": round(float(auc), 4),
            "log_loss": round(float(ll), 4),
            "top_features": top_features,
        },
    }


# ── Persistence ──────────────────────────────────────────────────────────────

def save_model(model_data: dict, path: str | None = None):
    path = path or config.MODEL_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(model_data, f, indent=2)
    print(f"Model saved → {path}")


def load_model(path: str | None = None) -> dict:
    path = path or config.MODEL_PATH
    with open(path, "r") as f:
        return json.load(f)
