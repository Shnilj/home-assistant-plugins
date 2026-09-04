"""Motion / change detection, restricted to a region of interest (the bowls).

Uses a MOG2 background subtractor. Only pixels inside the ROI are considered,
so movement elsewhere in the frame (a curtain, someone walking past) does not
trigger captures.
"""
from __future__ import annotations

import cv2
import numpy as np


def clamp_roi(roi, frame_shape):
    """Clamp [x, y, w, h] to the frame; return None if invalid/whole-frame."""
    if not roi:
        return None
    h, w = frame_shape[:2]
    x, y, rw, rh = roi
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))
    rw = max(1, min(int(rw), w - x))
    rh = max(1, min(int(rh), h - y))
    if rw < 8 or rh < 8:
        return None
    return [x, y, rw, rh]


class MotionDetector:
    def __init__(self, sensitivity: int = 25, min_area: int = 1500):
        # Higher sensitivity (1-100) -> lower pixel threshold -> more sensitive.
        self.var_threshold = max(4, int(64 - (sensitivity / 100.0) * 56))
        self.min_area = min_area
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=300, varThreshold=self.var_threshold, detectShadows=False
        )

    def process(self, frame, roi=None):
        """Return (motion: bool, area: int, bbox or None) for the ROI.

        bbox is [x, y, w, h] in FULL-FRAME coordinates around the largest
        changed blob, suitable for cropping the cat.
        """
        roi = clamp_roi(roi, frame.shape)
        if roi is None:
            region = frame
            ox, oy = 0, 0
        else:
            x, y, w, h = roi
            region = frame[y : y + h, x : x + w]
            ox, oy = x, y

        gray = cv2.GaussianBlur(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        mask = self._bg.apply(gray)
        # Drop low-confidence pixels, then close gaps.
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1
        )
        mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return False, 0, None

        largest = max(contours, key=cv2.contourArea)
        area = int(cv2.contourArea(largest))
        if area < self.min_area:
            return False, area, None

        bx, by, bw, bh = cv2.boundingRect(largest)
        bbox = [bx + ox, by + oy, bw, bh]
        return True, area, bbox
