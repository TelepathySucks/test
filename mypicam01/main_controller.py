"""Main controller orchestrating camera capture and event detection."""


import os
import subprocess
import threading
import time

from picamera2 import Picamera2

from frame_buffer import FrameBuffer
from flash_detector import FlashDetector
from laser_detector import LaserDetector


class MainController:
    """Handle camera capture, detection, and alerts."""

    def __init__(self, config):
        self.picam2 = Picamera2()
        self.config = config
        self.buffer = FrameBuffer(config["buffer"])
        self.flash_detector = FlashDetector(config["detection"])
        self.laser_detector = LaserDetector(config["detection"])
        self.trigger_callback = None

        self.last_frame = None
        self.last_frame_lock = threading.Lock()
        self.stream_lock = threading.Lock()
        self.config_lock = threading.Lock()

        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        """Begin capturing frames."""
        with self.stream_lock:
            if self.thread and self.thread.is_alive():
                return

            self.stop_event.clear()
            self._apply_camera_config()
            self.picam2.start()
            self.thread = threading.Thread(
                target=self.run_loop,
                daemon=True,
            )
            self.thread.start()

    def _apply_camera_config(self):
        with self.config_lock:
            camera_cfg = self.config["camera"].copy()

        self.picam2.configure(
            self.picam2.create_video_configuration(
                main={
                    "size": camera_cfg["resolution"],
                    "format": "RGB888",
                },
                controls={
                    "FrameDurationLimits": (
                        int(1e6 / camera_cfg["fps"]),
                        int(1e6 / camera_cfg["fps"]),
                    ),
                    "AnalogueGain": camera_cfg["gain"],
                    "ExposureTime": camera_cfg["exposure"],
                },
            )
        )

    def reconfigure_camera(self, new_camera_config):
        """Apply new camera settings safely."""
        with self.stream_lock:
            self.stop_event.set()
            if self.thread:
                self.thread.join()

            self.picam2.stop()
            with self.config_lock:
                self.config["camera"].update(new_camera_config)

            self._apply_camera_config()
            self.picam2.start()

            self.stop_event.clear()
            self.thread = threading.Thread(
                target=self.run_loop,
                daemon=True,
            )
            self.thread.start()

    def run_loop(self):
        """Capture frames and check for events until stopped."""
        while not self.stop_event.is_set():
            try:
                frame = self.picam2.capture_array()
            except Exception as exc:  # noqa: BLE001
                print(f"[RUN] capture error: {exc}")
                time.sleep(0.1)
                continue

            timestamp = time.time()
            with self.last_frame_lock:
                self.last_frame = frame.copy()
            self.buffer.add_frame(frame, timestamp)

            with self.config_lock:
                detection_cfg = self.config["detection"].copy()

            if self.flash_detector.check(frame):
                if detection_cfg.get("autosave_flash"):
                    self.buffer.save_to_file()
                if detection_cfg.get("sound_flash"):
                    self.play_alert("flash")
                if self.trigger_callback:
                    self.trigger_callback("Flash Detected")

            if self.laser_detector.check(frame):
                if detection_cfg.get("autosave_laser"):
                    self.buffer.save_to_file()
                if detection_cfg.get("sound_laser"):
                    self.play_alert("laser")
                if self.trigger_callback:
                    self.trigger_callback("Laser Detected")

            with self.config_lock:
                fps = self.config["camera"].get("fps", 10)
            time.sleep(1 / fps)

    def stop(self):
        """Stop capturing and close resources."""
        with self.stream_lock:
            self.stop_event.set()
            if self.thread:
                self.thread.join()
            self.picam2.stop()
            self.picam2.close()

    def set_trigger_callback(self, callback):
        self.trigger_callback = callback

    def get_last_frame(self):
        with self.last_frame_lock:
            if self.last_frame is None:
                return None
            return self.last_frame.copy()

    def play_alert(self, kind):
        """Play an alert sound asynchronously if available."""
        sound_file = f"sounds/{kind}.wav"
        if os.path.exists(sound_file):
            subprocess.Popen(
                ["aplay", sound_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
