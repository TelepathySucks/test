"""In-memory rolling video buffer for pre/post event recording."""

import datetime
import os
import threading
from collections import deque

import cv2

class FrameBuffer:
    """Maintain a fixed-size deque of frames for quick saving."""

    def __init__(self, config):
        """Create the buffer according to ``config``."""
        self.buffer_seconds = config.get('length', 5)
        self.fps = config.get('fps', 10)
        self.max_frames = int(self.buffer_seconds * self.fps)
        self.frames = deque(maxlen=self.max_frames)
        self.lock = threading.Lock()
        self.output_dir = "captures"
        os.makedirs(self.output_dir, exist_ok=True)

    def update_config(self, fps=None, length=None):
        """Adjust buffer settings such as FPS and length safely."""
        with self.lock:
            if fps is not None:
                self.fps = fps
            if length is not None:
                self.buffer_seconds = length
            new_max = int(self.buffer_seconds * self.fps)
            if new_max != self.max_frames:
                self.max_frames = new_max
                self.frames = deque(list(self.frames)[-self.max_frames:],
                                   maxlen=self.max_frames)

    def add_frame(self, frame, timestamp):
        """Append a frame and timestamp to the buffer."""
        with self.lock:
            self.frames.append((frame.copy(), timestamp))

    def save_to_file(self):
        """Write the buffered frames to an MP4 file."""
        with self.lock:
            if not self.frames:
                return

            now = datetime.datetime.now()
            filename = now.strftime("buffer_%Y%m%d_%H%M%S.mp4")
            filepath = os.path.join(self.output_dir, filename)

            height, width, _ = self.frames[0][0].shape
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(filepath, fourcc, self.fps, (width, height))

            for frame, _ in self.frames:
                writer.write(frame)
            writer.release()
            print(f"[BUFFER] Saved video to {filepath}")

    def estimate_memory_usage(self):
        """Return approximate buffer memory usage in megabytes."""
        if not self.frames:
            return 0
        h, w, c = self.frames[0][0].shape
        bytes_per_frame = h * w * c
        return round(bytes_per_frame * len(self.frames) / (1024 * 1024), 2)  # MB
