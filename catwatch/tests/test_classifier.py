import os

import cv2
import numpy as np

from app import classifier, config


def _sig_mode():
    classifier._MODE = "signature"


def test_signature_feature_dims():
    _sig_mode()
    img = np.full((80, 80, 3), (40, 70, 180), np.uint8)
    f = classifier.extract_feature(img)
    assert f is not None and f.shape[0] == 96


def test_kind_guard_blocks_stale_model(tmp_path):
    _sig_mode()
    p = str(tmp_path / "m.npz")
    np.savez(p, features=np.zeros((2, 1280), np.float32),
             labels=np.array(["a", "b"], object), kind="embedding")
    assert classifier.SignatureModel.load(p).ready is False


def _make_dataset():
    for name, color in (("A", (40, 70, 180)), ("B", (170, 70, 40))):
        d = os.path.join(config.DATASET_DIR, name)
        os.makedirs(d, exist_ok=True)
        for i in range(4):
            cv2.imwrite(os.path.join(d, f"{i}.jpg"), np.full((80, 80, 3), color, np.uint8))


def test_train_predict_and_evaluate():
    _sig_mode()
    _make_dataset()
    summary = classifier.train()
    assert summary["trained"] and summary["samples"] == 8
    model = classifier.SignatureModel.load()
    assert model.ready
    label, conf = model.predict(np.full((80, 80, 3), (40, 70, 180), np.uint8))
    assert label in ("A", "B") and 0.0 <= conf <= 1.0
    ev = classifier.evaluate()
    assert ev["total"] == 8 and "signature" in ev["recognizers"]
    assert 0.0 <= ev["recognizers"]["signature"]["accuracy"] <= 1.0
