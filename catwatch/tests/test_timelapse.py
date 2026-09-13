import os

import numpy as np
import pytest

from app import timelapse


def _frame(w=1280, h=720):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_clipbuffer_throttles_sampling():
    buf = timelapse.ClipBuffer(min_interval=0.5)
    buf.add(_frame(), now=0.0)
    buf.add(_frame(), now=0.1)   # too soon — ignored
    buf.add(_frame(), now=0.6)   # past the interval — kept
    assert len(buf) == 2


def test_clipbuffer_downscales_to_even_dims_within_maxwidth():
    buf = timelapse.ClipBuffer(max_width=480, min_interval=0.0)
    buf.add(_frame(1280, 720), now=0.0)
    w, h = buf.size
    assert w <= 480
    assert w % 2 == 0 and h % 2 == 0     # H.264 yuv420p needs even dimensions
    assert buf.frames[0].shape == (h, w, 3)


def test_clipbuffer_thins_when_capped():
    buf = timelapse.ClipBuffer(min_interval=0.5, max_frames=10)
    t = 0.0
    for _ in range(40):
        t += 0.5
        buf.add(_frame(), now=t)
    # Never grows unbounded, and the interval widened so coverage stays spread.
    assert len(buf) <= 10
    assert buf._interval > 0.5


def test_encode_returns_false_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(timelapse, "ffmpeg_available", lambda: False)
    assert timelapse.encode_mp4([_frame(16, 16)], (16, 16), "/tmp/none.mp4") is False


def test_encode_produces_playable_file(tmp_path):
    if not timelapse.ffmpeg_available():
        pytest.skip("ffmpeg not installed")
    frames = [_frame(64, 48) for _ in range(6)]
    out = str(tmp_path / "clip.mp4")
    assert timelapse.encode_mp4(frames, (64, 48), out, fps=8) is True
    assert os.path.getsize(out) > 0
