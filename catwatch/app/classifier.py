"""Local cat recognition.

Two feature backends, selected by the ``recognizer`` option:

- **embedding** (default): a MobileNetV2 run through OpenCV's DNN module turns
  each crop into a 1280-d feature vector. Far more discriminative than colour
  alone and largely robust to lighting. No extra dependency (OpenCV ships the DNN
  runtime); the model is bundled under ``models/``.
- **signature**: a lightweight colour/pattern histogram. No model file needed;
  fine when cats are very distinct and the host is tiny.

Both feed the same weighted k-nearest-neighbours over the labelled crops, so
training, storage and inference are identical — only the feature vector changes.
"""
from __future__ import annotations

import glob
import logging
import os
import threading

import cv2
import numpy as np

from . import config


def _knn_loo(feats, labels, k=5):
    """Leave-one-out weighted-kNN. Returns (preds, winning_shares)."""
    F = np.vstack(feats).astype(np.float32)
    sims = F @ F.T
    np.fill_diagonal(sims, -1.0)  # never let an image match itself
    preds, shares = [], []
    for i in range(len(labels)):
        idx = np.argsort(-sims[i])[:k]
        votes = {}
        for j in idx:
            votes[labels[j]] = votes.get(labels[j], 0.0) + max(float(sims[i, j]), 0.0)
        if votes:
            w = max(votes, key=votes.get)
            preds.append(w)
            shares.append(votes[w] / (sum(votes.values()) + 1e-6))
        else:
            preds.append(None)
            shares.append(0.0)
    return preds, shares


def _gather_labelled(dataset_dir):
    """Return list of (label, path, bgr_image) for every labelled crop."""
    items = []
    for label in sorted(os.listdir(dataset_dir)):
        if label in config.RESERVED_LABELS:
            continue
        folder = os.path.join(dataset_dir, label)
        if not os.path.isdir(folder):
            continue
        for path in glob.glob(os.path.join(folder, "*.jpg")):
            img = cv2.imread(path)
            if img is not None:
                items.append((label, path, img))
    return items


def evaluate(dataset_dir: str = config.DATASET_DIR, k: int = 5, margin: float = 0.6):
    """Leave-one-out accuracy for each available recognizer, so you can see
    whether the neural recognizer really does better on YOUR cats."""
    items = _gather_labelled(dataset_dir)
    counts = {}
    for label, _, _ in items:
        counts[label] = counts.get(label, 0) + 1

    backends = {"signature": _signature}
    if os.path.exists(config.EMBED_MODEL_PATH):
        backends["embedding"] = _embed

    out = {"total": len(items), "per_cat_counts": counts, "margin": margin, "recognizers": {}}
    if len(items) < 2 or len(counts) < 2:
        out["note"] = "Need at least 2 cats with a few labelled crops each to evaluate."
        return out

    for name, fn in backends.items():
        feats, kept = [], []
        for label, path, img in items:
            try:
                f = fn(img)
            except Exception:  # noqa: BLE001
                f = None
            if f is not None:
                feats.append(f)
                kept.append((label, path))
        if len(kept) < 2:
            continue
        labels = [l for l, _ in kept]
        preds, shares = _knn_loo(feats, labels, k)

        correct = attributed = attributed_correct = 0
        confusion, mistakes = {}, []
        for (true, path), pred, share in zip(kept, preds, shares):
            confusion.setdefault(true, {})
            confusion[true][pred] = confusion[true].get(pred, 0) + 1
            if pred == true:
                correct += 1
            else:
                mistakes.append({"true": true, "pred": pred,
                                 "file": os.path.basename(path), "share": round(share, 2)})
            if share >= margin:
                attributed += 1
                if pred == true:
                    attributed_correct += 1
        n = len(kept)
        out["recognizers"][name] = {
            "n": n,
            "accuracy": round(correct / n, 3),
            "attributed": attributed,
            "abstained": n - attributed,
            "attributed_accuracy": round(attributed_correct / attributed, 3) if attributed else None,
            "confusion": confusion,
            "mistakes": sorted(mistakes, key=lambda m: m["share"], reverse=True)[:60],
        }
    return out

log = logging.getLogger("catwatch.classifier")

# --- feature backend state -------------------------------------------------
_MODE = "signature"          # resolved by init_recognizer()
_net = None
_net_lock = threading.Lock()
_embed_layer = "__unresolved__"  # cached penultimate-layer name, or None for default output

_IMN_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_IMN_STD = np.array([0.229, 0.224, 0.225], np.float32)
_PREFERRED_LAYER = "onnx_node!GlobalAveragePool_97"  # 1280-d pooled features


def init_recognizer(settings) -> str:
    """Choose the feature backend once at startup. Returns the active mode."""
    global _MODE
    want = getattr(settings, "recognizer", "embedding")
    if want == "embedding" and os.path.exists(config.EMBED_MODEL_PATH):
        try:
            _load_net()
            _MODE = "embedding"
            log.info("Recognizer: embedding (MobileNetV2 via OpenCV DNN)")
            return _MODE
        except Exception as exc:  # noqa: BLE001
            log.warning("Embedding model failed to load (%s); using signature", exc)
    elif want == "embedding":
        log.warning("Embedding model not found at %s; using signature", config.EMBED_MODEL_PATH)
    _MODE = "signature"
    log.info("Recognizer: signature (colour/pattern)")
    return _MODE


def current_mode() -> str:
    return _MODE


# --- embedding backend -----------------------------------------------------
def _load_net():
    global _net
    if _net is None:
        _net = cv2.dnn.readNetFromONNX(config.EMBED_MODEL_PATH)
    return _net


def _embed(crop):
    global _embed_layer
    net = _load_net()
    img = cv2.resize(crop, (224, 224))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img = (img - _IMN_MEAN) / _IMN_STD
    blob = img.transpose(2, 0, 1)[None]
    with _net_lock:
        net.setInput(blob)
        if _embed_layer == "__unresolved__":
            try:
                out = net.forward(_PREFERRED_LAYER)
                _embed_layer = _PREFERRED_LAYER
            except cv2.error:
                out = net.forward()
                _embed_layer = None
        else:
            out = net.forward(_embed_layer) if _embed_layer else net.forward()
    v = out.flatten().astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-6)


# --- signature backend -----------------------------------------------------
_INPUT = 64
_GRID = 4


def _signature(crop):
    img = cv2.resize(crop, (_INPUT, _INPUT), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h_hist = cv2.calcHist([hsv], [0], None, [24], [0, 180]).flatten()
    s_hist = cv2.calcHist([hsv], [1], None, [24], [0, 256]).flatten()
    h_hist /= h_hist.sum() + 1e-6
    s_hist /= s_hist.sum() + 1e-6
    cell = _INPUT // _GRID
    grid = []
    for gy in range(_GRID):
        for gx in range(_GRID):
            m = hsv[gy * cell:(gy + 1) * cell, gx * cell:(gx + 1) * cell].reshape(-1, 3).mean(axis=0)
            grid.extend([m[0] / 180.0, m[1] / 255.0, m[2] / 255.0])
    feat = np.concatenate([h_hist, s_hist, np.asarray(grid, dtype=np.float32)])
    return (feat / (np.linalg.norm(feat) + 1e-6)).astype(np.float32)


def extract_feature(crop):
    """Return an L2-normalised feature vector for a BGR crop, or None."""
    if crop is None or getattr(crop, "size", 0) == 0:
        return None
    try:
        return _embed(crop) if _MODE == "embedding" else _signature(crop)
    except Exception as exc:  # noqa: BLE001
        log.warning("Feature extraction failed: %s", exc)
        return None


# --- kNN model over labelled crops -----------------------------------------
class SignatureModel:
    def __init__(self):
        self.features = None
        self.labels = []
        self.kind = _MODE

    @classmethod
    def load(cls, path: str = config.MODEL_PATH):
        model = cls()
        if os.path.exists(path):
            try:
                data = np.load(path, allow_pickle=True)
                kind = str(data["kind"]) if "kind" in data else "signature"
                if kind != _MODE:
                    log.warning(
                        "Saved model was trained with the '%s' recognizer but '%s' is active; "
                        "click Train to rebuild it.", kind, _MODE)
                    return model
                model.features = data["features"]
                model.labels = [str(x) for x in data["labels"]]
                model.kind = kind
                log.info("Loaded model: %d samples across %d cats (%s)",
                         len(model.labels), len(set(model.labels)), kind)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not load model (%s); starting empty", exc)
        return model

    @property
    def ready(self) -> bool:
        return self.features is not None and len(self.labels) > 0

    def predict(self, crop, k: int = 5):
        feat = extract_feature(crop)
        if feat is None or not self.ready or feat.shape[0] != self.features.shape[1]:
            return "unknown", 0.0
        sims = self.features @ feat
        k = min(k, len(self.labels))
        top = np.argsort(-sims)[:k]
        votes = {}
        for i in top:
            votes[self.labels[i]] = votes.get(self.labels[i], 0.0) + max(float(sims[i]), 0.0)
        winner = max(votes, key=votes.get)
        share = votes[winner] / (sum(votes.values()) + 1e-6)
        return winner, round(float(share * max(sims.max(), 0.0)), 3)


def train(dataset_dir: str = config.DATASET_DIR, model_path: str = config.MODEL_PATH):
    features, labels, per_cat = [], [], {}
    for label in sorted(os.listdir(dataset_dir)):
        if label in config.RESERVED_LABELS:
            continue
        folder = os.path.join(dataset_dir, label)
        if not os.path.isdir(folder):
            continue
        count = 0
        for path in glob.glob(os.path.join(folder, "*.jpg")):
            feat = extract_feature(cv2.imread(path))
            if feat is not None:
                features.append(feat)
                labels.append(label)
                count += 1
        if count:
            per_cat[label] = count

    if not features:
        log.warning("No labelled images in %s; model not written", dataset_dir)
        return {"trained": False, "samples": 0, "cats": {}, "recognizer": _MODE}

    arr = np.vstack(features).astype(np.float32)
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    np.savez(model_path, features=arr, labels=np.array(labels, dtype=object), kind=_MODE)
    log.info("Trained %s model on %d samples: %s", _MODE, len(labels), per_cat)
    return {"trained": True, "samples": len(labels), "cats": per_cat, "recognizer": _MODE}
