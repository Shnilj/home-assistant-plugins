"""Timelapse clips of a visit.

While a cat is at a bowl we buffer downscaled frames; when the visit is counted
as a meal/drink we encode a short, sped-up MP4 (H.264, browser- and Home
Assistant-playable) so you can watch what actually happened, not just a single
still.

Encoding uses the ``ffmpeg`` binary (installed in the add-on image) via a raw
pipe — no extra Python dependency. If ffmpeg is missing, clip capture is simply
skipped and everything else works as before.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

import cv2
import numpy as np

log = logging.getLogger("catwatch.timelapse")

_FFMPEG = "__unresolved__"


def ffmpeg_available() -> bool:
    """True if the ffmpeg binary is on PATH (cached after the first check)."""
    global _FFMPEG
    if _FFMPEG == "__unresolved__":
        _FFMPEG = shutil.which("ffmpeg")
    return _FFMPEG is not None


class ClipBuffer:
    """Accumulates frames for one visit.

    Frames are sampled no more often than ``min_interval`` seconds, downscaled to
    at most ``max_width`` (with even dimensions, required by H.264 yuv420p), and
    capped at ``max_frames``. When the cap is hit the buffer is halved and the
    sampling interval doubled, so a very long visit still yields one clip that
    spans the whole visit rather than only its start.
    """

    def __init__(self, max_width: int = 480, min_interval: float = 0.5, max_frames: int = 240):
        self.max_width = max_width
        self.min_interval = float(min_interval)
        self.max_frames = max_frames
        self.frames: list[np.ndarray] = []
        self.size: tuple[int, int] | None = None
        self._last: float | None = None
        self._interval = float(min_interval)

    def _fit(self, frame):
        h, w = frame.shape[:2]
        if self.size is None:
            scale = min(1.0, self.max_width / float(w or 1))
            nw = max(2, (int(round(w * scale)) // 2) * 2)
            nh = max(2, (int(round(h * scale)) // 2) * 2)
            self.size = (nw, nh)
        nw, nh = self.size
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(resized)

    def add(self, frame, now: float) -> None:
        if frame is None:
            return
        if self._last is not None and now - self._last < self._interval:
            return
        try:
            fitted = self._fit(frame)
        except cv2.error:
            return
        self._last = now
        self.frames.append(fitted)
        if len(self.frames) > self.max_frames:
            self.frames = self.frames[::2]   # thin, keep whole-visit coverage
            # Widen future spacing to match the thinned buffer (never below a
            # floor, so thinning still slows sampling even at min_interval 0).
            self._interval = max(self._interval * 2, self.min_interval * 2, 1.0)

    def __len__(self) -> int:
        return len(self.frames)


def encode_mp4(frames, size, out_path: str, fps: int = 8) -> bool:
    """Encode buffered BGR frames to an H.264 MP4. Returns True on success."""
    if not frames or size is None or not ffmpeg_available():
        return False
    w, h = size
    fps = max(1, int(fps))
    cmd = [
        _FFMPEG, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
        "-i", "-", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-movflags", "+faststart",
        out_path,
    ]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for f in frames:
            proc.stdin.write(f.tobytes())
        proc.stdin.close()
        err = proc.stderr.read()
        rc = proc.wait(timeout=90)
    except Exception as exc:  # noqa: BLE001
        log.warning("Timelapse encode failed: %s", exc)
        return False
    if rc != 0:
        log.warning("ffmpeg exited %s: %s", rc, err.decode("utf-8", "ignore")[:300])
        return False
    return True
