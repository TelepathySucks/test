"""Laser-spot detection."""

import cv2
import numpy as np

class LaserDetector:
    """Detect focused bright spots against a dark background."""

    def __init__(self, config):
        """Create the detector with configuration options."""
        self.threshold = config.get('laser_threshold', 50)
        self.min_blob = config.get('min_blob', 5)
        self.max_blob = config.get('max_blob', 100)
        self.background = None
        self.alpha = 0.95  # Background blend weight (0 = no memory, 1 = static bg)

    def check(self, frame):
        """Return ``True`` if a laser spot is detected in ``frame``."""
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        if self.background is None:
            self.background = gray.astype(np.float32)
            return False

        # Update background model
        cv2.accumulateWeighted(gray, self.background, self.alpha)
        bg = cv2.convertScaleAbs(self.background)

        # Find bright spots
        diff = cv2.subtract(gray, bg)
        _, thresh = cv2.threshold(diff, self.threshold, 255, cv2.THRESH_BINARY)

        # Filter by contour size (to avoid single pixel noise)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if self.min_blob < area < self.max_blob:
                return True  # Triggered

        return False
