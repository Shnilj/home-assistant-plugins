"""Local cat recognition — colour/pattern signature classifier.

Deliberately lightweight: no deep-learning runtime, no downloaded weights, runs
comfortably on a Raspberry Pi, and works well when the cats are visually
distinct (different colours / markings). Each labelled crop becomes a feature
vector; recognition is weighted k-nearest-neighbours by cosine similarity.

If you later want to tell apart cats that look very similar, this module is the
single place to swap in an embedding model (e.g. a MobileNet feature extractor
via onnxruntime): keep ``extract_feature`` returning an L2-normalised vector and
everything else — training, storage, inference — stays the same. See DOCS.md.
"""
from __future__ import annotations

import glob
import logging
import os

import cv2
import numpy as np

from . import config

log = logging.getLogger("catwatch.classifier")

_INPUT = 64
_GRID = 4  # 4x4 spatial colour grid


def extract_feature(crop):
    """Return an L2-normalised feature vector for a BGR crop, or None."""
    if crop is None or getattr(crop, "size", 0) == 0:
        return None
    img = cv2.resize(crop, (_INPUT, _INPUT), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Global hue / saturation histograms (colour identity).
    h_hist = cv2.calcHist([hsv], [0], None, [24], [0, 180]).flatten()
    s_hist = cv2.calcHist([hsv], [1], None, [24], [0, 256]).flatten()
    h_hist /= h_hist.sum() + 1e-6
    s_hist /= s_hist.sum() + 1e-6

    # Coarse spatial grid of mean HSV (where markings sit on the body).
    cell = _INPUT // _GRID
    grid = []
    for gy in range(_GRID):
        for gx in range(_GRID):
            cellimg = hsv[
                gy * cell : (gy + 1) * cell, gx * cell : (gx + 1) * cell
            ]
            m = cellimg.reshape(-1, 3).mean(axis=0)
            grid.extend([m[0] / 180.0, m[1] / 255.0, m[2] / 255.0])

    feat = np.concatenate([h_hist, s_hist, np.asarray(grid, dtype=np.float32)])
    norm = np.linalg.norm(feat) + 1e-6
    return (feat / norm).astype(np.float32)


class SignatureModel:
    def __init__(self):
        self.features = None  # (N, D) float32
        self.labels = []      # list[str]

    @classmethod
    def load(cls, path: str = config.MODEL_PATH):
        model = cls()
        if os.path.exists(path):
            try:
                data = np.load(path, allow_pickle=True)
                model.features = data["features"]
                model.labels = [str(x) for x in data["labels"]]
                log.info(
                    "Loaded model: %d samples across %d cats",
                    len(model.labels),
                    len(set(model.labels)),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not load model (%s); starting empty", exc)
        return model

    @property
    def ready(self) -> bool:
        return self.features is not None and len(self.labels) > 0

    def predict(self, crop, k: int = 5):
        """Return (label, confidence 0-1). label is 'unknown' if not ready."""
        feat = extract_feature(crop)
        if feat is None or not self.ready:
            return "unknown", 0.0
        sims = self.features @ feat  # cosine similarity (both normalised)
        k = min(k, len(self.labels))
        top = np.argsort(-sims)[:k]
        votes = {}
        for i in top:
            votes[self.labels[i]] = votes.get(self.labels[i], 0.0) + max(
                float(sims[i]), 0.0
            )
        winner = max(votes, key=votes.get)
        share = votes[winner] / (sum(votes.values()) + 1e-6)
        confidence = round(float(share * max(sims.max(), 0.0)), 3)
        return winner, confidence


def train(dataset_dir: str = config.DATASET_DIR, model_path: str = config.MODEL_PATH):
    """Build the model from labelled crops. Returns a summary dict."""
    features, labels = [], []
    per_cat = {}
    for label in sorted(os.listdir(dataset_dir)):
        if label in config.RESERVED_LABELS:
            continue
        folder = os.path.join(dataset_dir, label)
        if not os.path.isdir(folder):
            continue
        count = 0
        for path in glob.glob(os.path.join(folder, "*.jpg")):
            img = cv2.imread(path)
            feat = extract_feature(img)
            if feat is not None:
                features.append(feat)
                labels.append(label)
                count += 1
        if count:
            per_cat[label] = count

    if not features:
        log.warning("No labelled images found in %s; model not written", dataset_dir)
        return {"trained": False, "samples": 0, "cats": {}}

    arr = np.vstack(features).astype(np.float32)
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    np.savez(model_path, features=arr, labels=np.array(labels, dtype=object))
    log.info("Trained model on %d samples: %s", len(labels), per_cat)
    return {"trained": True, "samples": len(labels), "cats": per_cat}
