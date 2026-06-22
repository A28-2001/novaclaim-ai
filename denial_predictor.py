"""
denial_predictor.py
===================
Scikit-learn ML pipeline predicting prior authorization denial risk.

Two models are trained and ensembled:
  - LogisticRegression  : interpretable baseline, good with limited data
  - RandomForestClassifier : captures non-linear feature interactions

Features (all derivable from a parsed document, no external APIs needed):
  completeness_score    — fraction of required fields present (0.0–1.0)
  has_npi               — provider NPI present (0/1)
  has_cpt               — CPT procedure code present (0/1)
  has_diagnosis         — ICD-10 diagnosis code present (0/1)
  has_auth_number       — authorization number present (0/1)
  has_member_id         — insurance member ID present (0/1)
  has_facility          — facility name present (0/1)
  validation_errors     — count of hard validation errors
  validation_warnings   — count of validation warnings
  payor_approval_rate   — historical approval rate for this payor (0.0–1.0)

Target: binary — 1 = Denied, 0 = Approved
(Pending records are excluded from training; predicted at inference time)

Usage in Home.py:
    from denial_predictor import DenialPredictor
    predictor = DenialPredictor()
    trained = predictor.fit_from_db()
    if trained:
        prob = predictor.predict_proba_denial(pa_result, validation_issues)
        label, color = predictor.denial_risk_label(prob)
"""

import json
import os
import sqlite3
from typing import Optional

import numpy as np
import pandas as pd

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, roc_auc_score
    from sklearn.model_selection import cross_val_score, train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

DB_PATH = os.path.join(os.path.dirname(__file__), "prior_auth.db")

# Fields used to compute completeness — mirrors risk_scorer.py
REQUIRED_FIELDS = [
    "patient_name", "date_of_birth", "member_id", "provider_name",
    "provider_npi", "facility_name", "diagnosis_code", "treatment_requested",
    "cpt_code", "payor", "plan_name", "approval_status",
]

FEATURE_NAMES = [
    "completeness_score",
    "has_npi",
    "has_cpt",
    "has_diagnosis",
    "has_auth_number",
    "has_member_id",
    "has_facility",
    "validation_errors",
    "validation_warnings",
    "payor_approval_rate",
]


# ── Feature extraction ────────────────────────────────────────────────────────

def extract_features(row: dict, payor_rate_map: dict) -> dict:
    """
    Convert a raw database record (or pa_result dict) into a flat feature dict.
    All values are numeric so they can be fed directly into sklearn estimators.
    """
    completeness = sum(1 for f in REQUIRED_FIELDS if row.get(f)) / len(REQUIRED_FIELDS)
    payor = (row.get("payor") or "").strip()

    return {
        "completeness_score":  completeness,
        "has_npi":             1 if row.get("provider_npi") else 0,
        "has_cpt":             1 if row.get("cpt_code") else 0,
        "has_diagnosis":       1 if row.get("diagnosis_code") else 0,
        "has_auth_number":     1 if row.get("authorization_number") else 0,
        "has_member_id":       1 if row.get("member_id") else 0,
        "has_facility":        1 if row.get("facility_name") else 0,
        "validation_errors":   int(row.get("validation_errors", 0) or 0),
        "validation_warnings": int(row.get("validation_warnings", 0) or 0),
        "payor_approval_rate": payor_rate_map.get(payor, 0.65),  # 65% industry default
    }


# ── Predictor class ───────────────────────────────────────────────────────────

class DenialPredictor:
    """
    Ensemble denial predictor.

    When >= 20 labelled records exist in the database, trains a
    LogisticRegression + RandomForest ensemble.  Below that threshold,
    falls back to a rule-based score derived from completeness and
    validation error counts.
    """

    MIN_TRAINING_SAMPLES = 20

    def __init__(self):
        self.is_fitted = False
        self._payor_rate_map: dict = {}
        self._lr: Optional[Pipeline] = None
        self._rf: Optional[RandomForestClassifier] = None
        self.n_training_samples: int = 0
        self.cv_auc: float = 0.0
        self.holdout_report: str = ""

    # ── Training ──────────────────────────────────────────────────────────────

    def fit_from_db(self, db_path: str = DB_PATH) -> bool:
        """
        Load Approved/Denied records from SQLite, train both models.
        Returns True if trained successfully, False if insufficient data.
        """
        if not SKLEARN_AVAILABLE:
            return False

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM records
            WHERE LOWER(approval_status) IN ('approved', 'denied')
        """).fetchall()
        conn.close()

        records = [dict(r) for r in rows]
        if len(records) < self.MIN_TRAINING_SAMPLES:
            return False

        self._build_payor_rates(records)
        X, y = self._build_matrix(records)
        return self._train(X, y)

    def fit_on_dataframe(self, df: pd.DataFrame) -> bool:
        """
        Train directly from a DataFrame.
        Required: columns matching FEATURE_NAMES + a 'label' column (0=Approved, 1=Denied).
        Used in analysis.ipynb for demonstration.
        """
        if not SKLEARN_AVAILABLE:
            return False
        X = df[FEATURE_NAMES].values
        y = df["label"].values
        self._payor_rate_map = {}  # not used in this path
        return self._train(X, y)

    def _build_payor_rates(self, records: list):
        """Compute per-payor historical approval rate from training data."""
        counts: dict = {}
        for r in records:
            payor = (r.get("payor") or "").strip()
            if not payor:
                continue
            if payor not in counts:
                counts[payor] = {"approved": 0, "total": 0}
            counts[payor]["total"] += 1
            if (r.get("approval_status") or "").lower() == "approved":
                counts[payor]["approved"] += 1

        self._payor_rate_map = {
            p: v["approved"] / v["total"]
            for p, v in counts.items()
            if v["total"] >= 3
        }

    def _build_matrix(self, records: list):
        """Return (X numpy array, y numpy array) from a list of record dicts."""
        rows = [extract_features(r, self._payor_rate_map) for r in records]
        df = pd.DataFrame(rows)[FEATURE_NAMES]
        X = df.values
        y = np.array([
            1 if (r.get("approval_status") or "").lower() == "denied" else 0
            for r in records
        ])
        return X, y

    def _train(self, X, y) -> bool:
        """Fit both models, run cross-validation, store evaluation metrics."""
        if len(np.unique(y)) < 2:
            return False  # only one class — can't train

        self._lr = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
        ])
        self._rf = RandomForestClassifier(
            n_estimators=150,
            max_depth=6,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=42,
        )

        n_cv = min(5, len(y) // max(1, int(y.sum())))
        if n_cv >= 2:
            scores = cross_val_score(self._rf, X, y, cv=n_cv, scoring="roc_auc")
            self.cv_auc = float(scores.mean())

        # Holdout evaluation if enough data
        if len(y) >= 40:
            X_tr, X_te, y_tr, y_te = train_test_split(
                X, y, test_size=0.2, stratify=y, random_state=42
            )
            self._lr.fit(X_tr, y_tr)
            self._rf.fit(X_tr, y_tr)
            y_pred = (self.predict_proba_array(X_te) >= 0.5).astype(int)
            self.holdout_report = classification_report(y_te, y_pred,
                                                        target_names=["Approved", "Denied"])
            # Refit on full data
            self._lr.fit(X, y)
            self._rf.fit(X, y)
        else:
            self._lr.fit(X, y)
            self._rf.fit(X, y)

        self.n_training_samples = len(y)
        self.is_fitted = True
        return True

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict_proba_array(self, X: np.ndarray) -> np.ndarray:
        """Return ensemble denial probabilities for a feature matrix."""
        p_lr = self._lr.predict_proba(X)[:, 1]
        p_rf = self._rf.predict_proba(X)[:, 1]
        return (p_lr + p_rf) / 2

    def predict_proba_denial(
        self,
        pa_result: dict,
        validation_issues: Optional[list] = None,
    ) -> float:
        """
        Return probability of denial for a single parsed document (0.0–1.0).

        If the model is not yet trained (insufficient history), falls back to
        a rule-based score derived from completeness and validation errors.
        """
        issues = validation_issues or []
        record = dict(pa_result)
        record["validation_errors"]   = sum(1 for i in issues if i.get("severity") == "error")
        record["validation_warnings"] = sum(1 for i in issues if i.get("severity") == "warning")

        if self.is_fitted and SKLEARN_AVAILABLE:
            feats = extract_features(record, self._payor_rate_map)
            x = np.array([[feats[f] for f in FEATURE_NAMES]])
            return float(self.predict_proba_array(x)[0])

        # Rule-based fallback
        completeness = sum(1 for f in REQUIRED_FIELDS if record.get(f)) / len(REQUIRED_FIELDS)
        errors = record.get("validation_errors", 0) or 0
        raw = (1.0 - completeness) * 0.7 + min(errors * 0.1, 0.3)
        return min(1.0, max(0.0, raw))

    # ── Explainability ────────────────────────────────────────────────────────

    def feature_importance(self) -> list[tuple]:
        """Return [(feature_name, importance_score), ...] sorted descending."""
        if not self.is_fitted or self._rf is None:
            return []
        return sorted(
            zip(FEATURE_NAMES, self._rf.feature_importances_),
            key=lambda x: x[1],
            reverse=True,
        )

    def logistic_coefficients(self) -> list[tuple]:
        """Return [(feature_name, coefficient), ...] from LR — shows direction of effect."""
        if not self.is_fitted or self._lr is None:
            return []
        coefs = self._lr.named_steps["clf"].coef_[0]
        return sorted(
            zip(FEATURE_NAMES, coefs),
            key=lambda x: abs(x[1]),
            reverse=True,
        )

    # ── Labelling helpers ─────────────────────────────────────────────────────

    @staticmethod
    def denial_risk_label(prob: float) -> tuple[str, str]:
        """Return (label, hex_color) for a denial probability."""
        if prob < 0.25:
            return "Low Risk",      "#1D9E75"
        elif prob < 0.50:
            return "Moderate Risk", "#BA7517"
        elif prob < 0.75:
            return "High Risk",     "#E24B4A"
        else:
            return "Critical Risk", "#7f1d1d"

    def summary(self) -> str:
        status = "Trained" if self.is_fitted else "Not trained (insufficient data — using rule-based fallback)"
        lines = [
            f"DenialPredictor status : {status}",
            f"Training samples       : {self.n_training_samples}",
            f"Cross-val ROC-AUC      : {self.cv_auc:.3f}" if self.cv_auc else "",
        ]
        if self.holdout_report:
            lines += ["", "Holdout classification report:", self.holdout_report]
        return "\n".join(l for l in lines if l is not None)
