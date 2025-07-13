"""Main controller for camera capture, detection and buffering."""

import os
import subprocess
import threading
import time

from picamera2 import Picamera2
from frame_buffer import FrameBuffer
from flash_detector import FlashDetector
from laser_detector import LaserDetector

class MainController:
    """High level control of capture, detection and buffering."""

    def __init__(self, config):
        """Initialize controller from a configuration dictionary."""
        self.picam2 = Picamera2()
        self.config = config
        self.buffer = FrameBuffer(config['buffer'])
        self.flash_detector = FlashDetector(config['detection'])
        self.laser_detector = LaserDetector(config['detection'])
        self.running = False
        self.trigger_callback = None
        self.last_frame = None
        self.last_frame_lock = threading.Lock()
        self.stream_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        """Begin capturing frames and processing detections."""
        with self.stream_lock:
            if self.running:
                return
            self._apply_camera_config()
            self.picam2.start()
            self.running = True
            self.stop_event.clear()
            self.thread = threading.Thread(target=self.run_loop, daemon=True)
            self.thread.start()

    def _apply_camera_config(self):
        """Configure the underlying ``Picamera2`` instance."""
        cfg = self.config['camera']
        controls = {
            "FrameDurationLimits": (
                int(1e6 / cfg['fps']),
                int(1e6 / cfg['fps'])
            ),
            "AnalogueGain": cfg['gain'],
            "ExposureTime": cfg['exposure'],
            "AwbEnable": cfg.get('awb', False),
            "AeEnable": cfg.get('ae', False),
            "NoiseReductionMode": 0,
            "Sharpness": cfg.get('sharpness', 0),
            "Contrast": cfg.get('contrast', 0),
            "Saturation": cfg.get('saturation', 0),
            "Brightness": cfg.get('brightness', 0),
        }
        if 'colour_gains' in cfg:
            controls['ColourGains'] = cfg['colour_gains']
        if 'denoise' in cfg:
            controls['NoiseReductionStrength'] = cfg['denoise']

        if cfg.get('demosaic') == 'off':
            self.picam2.configure(
                self.picam2.create_video_configuration(
                    main={"size": cfg['resolution'], "format": "RGB888"},
                    transform=None,
                    raw=True,
                )
            )
        else:
            self.picam2.configure(
                self.picam2.create_video_configuration(
                    main={"size": cfg['resolution'], "format": "RGB888"},
                    transform=None,
                    controls=controls,
                )
            )

        self.picam2.set_controls(controls)

    def reconfigure_camera(self, new_camera_config):
        """Safely update camera settings and restart the stream."""
        with self.stream_lock:
            self.running = False
            self.stop_event.set()
            if self.thread:
                self.thread.join()
            self.picam2.stop()
            old_fps = self.config['camera'].get('fps')
            self.config['camera'].update(new_camera_config)
            self._apply_camera_config()
            self.picam2.start()
            self.running = True
            self.stop_event.clear()
            self.thread = threading.Thread(target=self.run_loop, daemon=True)
            self.thread.start()

            # Adjust buffer FPS if changed
            if new_camera_config.get('fps') and new_camera_config['fps'] != old_fps:
                self.buffer.update_config(fps=new_camera_config['fps'])

    def update_detection(self, detection_cfg):
        """Update detection parameters for flash and laser detectors."""
        self.config['detection'].update(detection_cfg)
        self.flash_detector.threshold = self.config['detection'].get(
            'flash_threshold', self.flash_detector.threshold
        )
        self.laser_detector.threshold = self.config['detection'].get(
            'laser_threshold', self.laser_detector.threshold
        )
        self.laser_detector.min_blob = self.config['detection'].get(
            'min_blob', self.laser_detector.min_blob
        )
        self.laser_detector.max_blob = self.config['detection'].get(
            'max_blob', self.laser_detector.max_blob
        )

    def run_loop(self):
        """Capture frames continuously and run detection."""
        while not self.stop_event.is_set():
            try:
                frame = self.picam2.capture_array()
            except Exception:
                continue
            timestamp = time.time()
            with self.last_frame_lock:
                self.last_frame = frame.copy()
            self.buffer.add_frame(frame, timestamp)

            if self.flash_detector.check(frame):
                if self.config['detection']['autosave_flash']:
                    self.buffer.save_to_file()
                if self.config['detection']['sound_flash']:
                    self.play_alert('flash')
                if self.trigger_callback:
                    self.trigger_callback("Flash Detected")

            if self.laser_detector.check(frame):
                if self.config['detection']['autosave_laser']:
                    self.buffer.save_to_file()
                if self.config['detection']['sound_laser']:
                    self.play_alert('laser')
                if self.trigger_callback:
                    self.trigger_callback("Laser Detected")

            time.sleep(1 / self.config['camera']['fps'])

    def stop(self):
        """Stop capturing and shut down the camera."""
        with self.stream_lock:
            self.running = False
            self.stop_event.set()
            if self.thread:
                self.thread.join()
            self.picam2.stop()

    def set_trigger_callback(self, callback):
        """Set a callback to be invoked on detection events."""
        self.trigger_callback = callback

    def get_last_frame(self):
        """Return a copy of the most recently captured frame."""
        with self.last_frame_lock:
            return self.last_frame.copy() if self.last_frame is not None else None

    def play_alert(self, kind):
        """Play an alert sound if the corresponding file exists."""
        sound_file = f"sounds/{kind}.wav"
        if os.path.exists(sound_file):
            subprocess.Popen(
                ["aplay", sound_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
