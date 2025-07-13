"""Utility class for buffering frames in memory."""


import datetime
import os
import threading
from collections import deque


import cv2


class FrameBuffer:
    def __init__(self, config):
        self.buffer_seconds = config.get('length', 5)
        self.fps = config.get('fps', 10)
        self.max_frames = int(self.buffer_seconds * self.fps)
        self.frames = deque(maxlen=self.max_frames)
        self.lock = threading.Lock()
        self.output_dir = "captures"
        os.makedirs(self.output_dir, exist_ok=True)

    def add_frame(self, frame, timestamp):
        with self.lock:
            self.frames.append((frame.copy(), timestamp))

    def save_to_file(self):
        """Write buffered frames to an MP4 file without blocking capture."""
        with self.lock:
            if not self.frames:
                return

            frames = [f.copy() for f, _ in self.frames]
            height, width, _ = frames[0].shape

        now = datetime.datetime.now()
        filename = now.strftime("buffer_%Y%m%d_%H%M%S.mp4")
        filepath = os.path.join(self.output_dir, filename)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        try:
            writer = cv2.VideoWriter(
                filepath,
                fourcc,
                self.fps,
                (width, height),
            )

            for frame in frames:
                writer.write(frame)
            writer.release()
            print(f"[BUFFER] Saved video to {filepath}")
        except Exception as exc:  # noqa: BLE001
            print(f"[BUFFER] Failed to save video: {exc}")

    def estimate_memory_usage(self):
        if not self.frames:
            return 0
        h, w, c = self.frames[0][0].shape
        bytes_per_frame = h * w * c
        return round(bytes_per_frame * len(self.frames) / (1024 * 1024), 2)
        # value is in megabytes
