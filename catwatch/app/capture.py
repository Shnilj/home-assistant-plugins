"""RTSP capture with a background grabber thread.

VideoCapture buffers frames, which makes analysis lag behind reality. We run a
dedicated thread that continuously grabs and keeps only the newest frame, and
we reconnect automatically if the stream drops.
"""
from __future__ import annotations

import logging
import threading
import time

import cv2

log = logging.getLogger("catwatch.capture")


class RtspCamera:
    def __init__(self, url: str):
        self.url = url
        self._cap = None
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._connected = False

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="rtsp", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def connected(self) -> bool:
        return self._connected

    # -- frames -------------------------------------------------------------
    def read(self):
        """Return the most recent frame (numpy array) or None."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    # -- internals ----------------------------------------------------------
    def _open(self):
        # FFMPEG backend + TCP transport is the most reliable for RTSP.
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except cv2.error:
            pass
        return cap

    def _loop(self):
        backoff = 1.0
        while self._running:
            if not self.url:
                time.sleep(2)
                continue
            if self._cap is None or not self._cap.isOpened():
                log.info("Connecting to camera...")
                self._cap = self._open()
                if not self._cap.isOpened():
                    self._connected = False
                    log.warning("Camera not reachable, retrying in %.0fs", backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                log.info("Camera connected")
                backoff = 1.0

            ok, frame = self._cap.read()
            if not ok or frame is None:
                self._connected = False
                log.warning("Lost camera stream, reconnecting")
                self._cap.release()
                self._cap = None
                time.sleep(1)
                continue

            self._connected = True
            with self._lock:
                self._frame = frame
