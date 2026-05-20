from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score


def _threshold_signal_metrics(y_test: pd.Series, proba_up, min_probability: float) -> Dict[str, Any]:
    signals = []
    correct = []

    for actual, proba in zip(y_test.astype(int).tolist(), proba_up):
        if proba >= min_probability:
            signals.append("BUY")
            correct.append(actual == 1)
        elif proba <= (1 - min_probability):
            signals.append("SELL")
            correct.append(actual == 0)

    signal_trades = len(signals)
    total = len(y_test)
    accuracy = float(sum(correct) / signal_trades) if signal_trades else None

    return {
        "signal_trades": int(signal_trades),
        "signal_accuracy": accuracy,
        "signal_coverage": float(signal_trades / total) if total else 0.0,
        "min_probability": float(min_probability),
    }


def train_classifier(
    df: pd.DataFrame,
    features: list[str],
    model_path: str,
    min_probability: float = 0.58,
) -> Dict[str, Any]:
    data = df.dropna(subset=features + ["target_up"]).copy()
    if len(data) < 300:
        raise RuntimeError(f"ข้อมูลน้อยเกินไปสำหรับเทรน: {len(data)} rows ควรมีอย่างน้อย 300 rows")

    split = int(len(data) * 0.8)
    train = data.iloc[:split]
    test = data.iloc[split:]

    X_train = train[features]
    y_train = train["target_up"].astype(int)

    X_test = test[features]
    y_test = test["target_up"].astype(int)

    clf = RandomForestClassifier(
        n_estimators=350,
        max_depth=7,
        min_samples_leaf=12,
        random_state=42,
        class_weight="balanced_subsample",
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    pred = clf.predict(X_test)
    proba = clf.predict_proba(X_test)[:, 1]

    metrics: Dict[str, Any] = {
        "rows": int(len(data)),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "accuracy": float(accuracy_score(y_test, pred)),
        "roc_auc": float(roc_auc_score(y_test, proba)) if len(set(y_test)) > 1 else None,
        "features": features,
        "note": "metrics เป็นแค่ผลแบ่ง train/test ตามเวลา ไม่ใช่กำไรจริง ต้อง forward test ต่อ",
    }

    # เก็บ report แบบสั้น กัน JSON ยาวเกินในหน้าเว็บ
    report = classification_report(y_test, pred, output_dict=True)
    metrics["precision_1"] = float(report.get("1", {}).get("precision", 0.0))
    metrics["recall_1"] = float(report.get("1", {}).get("recall", 0.0))
    metrics.update(_threshold_signal_metrics(y_test, proba, min_probability))

    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": clf, "features": features, "metrics": metrics}, model_path)
    return metrics


def load_model(model_path: str) -> Dict[str, Any]:
    p = Path(model_path)
    if not p.exists():
        raise FileNotFoundError(f"ไม่พบโมเดล {model_path}")
    return joblib.load(p)
