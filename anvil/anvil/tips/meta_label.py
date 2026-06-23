"""Meta-labeling (López de Prado) — a calibrated ACT/ABSTAIN model on top of the PRIMARY signals.

It does NOT predict direction. Given features describing a primary call (which orthogonal factors fired,
their strengths, conviction, regime), it predicts **P(the primary call is correct)** — raising
accuracy-WHEN-IT-SPEAKS without a direction oracle (the honest mechanism behind ">75% when it speaks").

Pure-numpy logistic (standardized + L2), trained **OUT-OF-FOLD only** (no sample scores itself), and
**abstain-safe**: returns None until enough resolved labels accrue and both classes are present. This is
a Wave-I.4 building block — like calibration it is display/threshold only and must clear the SAME locked
battery + the orthogonality admission before it can gate emission, so it never games the gate.
"""

from __future__ import annotations

import numpy as np


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


class LogisticModel:
    """Standardized + L2-regularized logistic regression via batch gradient descent (no sklearn)."""

    def __init__(self, l2: float = 1.0):
        self.l2 = float(l2)
        self.coef: np.ndarray | None = None
        self.intercept = 0.0
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None

    def fit(self, X, y, *, iters: int = 800, lr: float = 0.3) -> "LogisticModel":
        X = np.asarray(X, dtype=float)
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        y = np.asarray(y, dtype=float).ravel()
        self.mean_ = X.mean(axis=0)
        self.std_ = X.std(axis=0)
        self.std_[self.std_ == 0] = 1.0
        xs = (X - self.mean_) / self.std_
        n, p = xs.shape
        w = np.zeros(p)
        b = 0.0
        for _ in range(iters):
            pr = _sigmoid(xs @ w + b)
            err = pr - y
            w -= lr * ((xs.T @ err) / n + self.l2 * w / n)
            b -= lr * float(err.mean())
        self.coef = w
        self.intercept = float(b)
        return self

    def predict_proba(self, X) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        xs = (X - self.mean_) / self.std_
        return _sigmoid(xs @ self.coef + self.intercept)


def oof_probabilities(X, y, *, k: int = 5, l2: float = 1.0, seed: int = 7):
    """K-fold OUT-OF-FOLD probabilities — the honest basis for ECE/accuracy (no row scores itself).
    None if there are too few samples for k folds."""
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    y = np.asarray(y, dtype=float).ravel()
    n = X.shape[0]
    if n < 2 * k:
        return None
    rng = np.random.default_rng(seed)
    folds = np.array_split(rng.permutation(n), k)
    oof = np.full(n, np.nan)
    for i in range(k):
        test = folds[i]
        train = np.concatenate([folds[j] for j in range(k) if j != i])
        if len(np.unique(y[train])) < 2:
            continue
        oof[test] = LogisticModel(l2).fit(X[train], y[train]).predict_proba(X[test])
    return oof


class MetaLabel:
    """A trained meta-labeler over NAMED features. Abstains (``predict`` → None) until fitted."""

    def __init__(self, feature_names, model: LogisticModel, n: int):
        self.feature_names = list(feature_names)
        self.model = model
        self.n = int(n)

    @classmethod
    def train(cls, rows, feature_names, label_key: str = "correct", *,
              l2: float = 1.0, min_samples: int = 60) -> "MetaLabel | None":
        """Train from resolved rows (each a dict of features + a 0/1 ``label_key``). None if too few
        rows or only one class present (can't meta-label without both outcomes)."""
        if len(rows) < int(min_samples):
            return None
        X = np.array([[float(r.get(f, 0.0) or 0.0) for f in feature_names] for r in rows], dtype=float)
        y = np.array([float(r.get(label_key, 0.0) or 0.0) for r in rows], dtype=float)
        if len(np.unique(y)) < 2:
            return None
        return cls(feature_names, LogisticModel(l2).fit(X, y), len(rows))

    def predict(self, features: dict) -> float | None:
        """P(primary call correct) for one feature dict; None if the model isn't fitted."""
        if self.model.coef is None:
            return None
        x = np.array([[float(features.get(f, 0.0) or 0.0) for f in self.feature_names]], dtype=float)
        return float(self.model.predict_proba(x)[0])
