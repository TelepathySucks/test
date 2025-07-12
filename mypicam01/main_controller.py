import time
import threading
import os
from picamera2 import Picamera2
from frame_buffer import FrameBuffer
from flash_detector import FlashDetector
from laser_detector import LaserDetector

class MainController:
    def __init__(self, config):
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

    def start(self):
        with self.stream_lock:
            self._apply_camera_config()
            self.picam2.start()
            self.running = True
            threading.Thread(target=self.run_loop, daemon=True).start()

    def _apply_camera_config(self):
        self.picam2.configure(self.picam2.create_video_configuration(
            main={"size": self.config['camera']['resolution'], "format": "RGB888"},
            controls={
                "FrameDurationLimits": (
                    int(1e6 / self.config['camera']['fps']),
                    int(1e6 / self.config['camera']['fps'])
                ),
                "AnalogueGain": self.config['camera']['gain'],
                "ExposureTime": self.config['camera']['exposure']
            }
        ))

    def reconfigure_camera(self, new_camera_config):
        with self.stream_lock:
            self.running = False
            self.picam2.stop()
            self.config['camera'].update(new_camera_config)
            self._apply_camera_config()
            self.picam2.start()
            self.running = True
            threading.Thread(target=self.run_loop, daemon=True).start()

    def run_loop(self):
        while self.running:
            frame = self.picam2.capture_array()
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
        with self.stream_lock:
            self.running = False
            self.picam2.stop()

    def set_trigger_callback(self, callback):
        self.trigger_callback = callback

    def get_last_frame(self):
        with self.last_frame_lock:
            return self.last_frame.copy() if self.last_frame is not None else None

    def play_alert(self, kind):
        sound_file = f"sounds/{kind}.wav"
        if os.path.exists(sound_file):
            os.system(f"aplay {sound_file} >/dev/null 2>&1 &")
