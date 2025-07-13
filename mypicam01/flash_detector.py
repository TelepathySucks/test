"""Bright-flash detection."""

import numpy as np

class FlashDetector:
    """Detect sudden increases in overall brightness."""

    def __init__(self, config):
        """Create the detector with configuration options."""
        self.threshold = config.get('flash_threshold', 5.0)
        self.history = []
        self.max_history = 10  # Average over last 10 frames

    def check(self, frame):
        """Return ``True`` if the frame triggers the flash detector."""
        gray = np.mean(frame)
        self.history.append(gray)

        if len(self.history) > self.max_history:
            self.history.pop(0)

        if len(self.history) < self.max_history:
            return False  # Not enough history yet

        avg = sum(self.history[:-1]) / (len(self.history) - 1)
        delta = gray - avg

        return delta > self.threshold
