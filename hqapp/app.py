"""Raspberry Pi HQ Camera Web Controller

Provides a Flask web interface for streaming the camera,
changing camera parameters, capturing images, recording video and
triggering alerts based on brightness events.

This application is intended to run on a Raspberry Pi 4 with an
IMX477 HQ camera using the Picamera2 library.
"""

import io
import os
import threading
import time
import logging
from collections import deque
from datetime import datetime

from flask import (Flask, Response, render_template, request, redirect,
                   url_for, session, jsonify)

try:
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput
    import cv2
    import numpy as np
except Exception as e:  # noqa: E722
    # Picamera2 is unavailable in the testing environment. We still allow
    # the module to be imported so the file can be syntax checked.
    Picamera2 = None  # type: ignore
    MJPEGEncoder = None  # type: ignore
    FileOutput = None  # type: ignore
    cv2 = None  # type: ignore
    np = None  # type: ignore
    logging.warning("Picamera2 or OpenCV not available: %s", e)


PASSWORD = "raspberry"  # simple authentication password
SECRET_KEY = "change-me"  # flask session secret

STREAM_FPS = 30
PRE_ROLL_SECONDS = 2
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")
os.makedirs(RECORDINGS_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = SECRET_KEY


class CameraController:
    """Manage Picamera2 operations in a thread."""

    def __init__(self):
        self.picam = Picamera2() if Picamera2 else None
        self.lock = threading.Lock()
        self.latest_frame = None
        self.frame_buffer = deque(maxlen=STREAM_FPS * PRE_ROLL_SECONDS)
        self.recording = False
        self.video_writer = None
        self.analysis_subscribers = []
        self.config = {
            "resolution": (640, 480),
            "gain": 1.0,
            "shutter": 1000,
            "brightness": 0,
            "fps": STREAM_FPS,
        }
        if self.picam:
            self.apply_settings()
            threading.Thread(target=self._capture_loop, daemon=True).start()
            threading.Thread(target=self._analysis_loop, daemon=True).start()

    def apply_settings(self):
        if not self.picam:
            return
        frame_dur = int(1_000_000 / self.config["fps"])
        if self.config["shutter"] > frame_dur:
            self.config["shutter"] = frame_dur
        conf = self.picam.create_video_configuration(
            main={"size": self.config["resolution"]},
            controls={
                "FrameDurationLimits": (frame_dur, frame_dur),
                "AnalogueGain": self.config["gain"],
                "ExposureTime": self.config["shutter"],
                "Brightness": self.config["brightness"],
            },
        )
        with self.lock:
            self.picam.configure(conf)

    def _capture_loop(self):
        self.picam.start()
        while True:
            frame = self.picam.capture_array()
            ret, jpeg = cv2.imencode(".jpg", frame) if cv2 else (False, None)
            if ret:
                with self.lock:
                    self.latest_frame = jpeg.tobytes()
                    self.frame_buffer.append(frame)
                    if self.recording and self.video_writer is not None:
                        self.video_writer.write(frame)
            time.sleep(1 / self.config["fps"])  # regulate FPS

    def _analysis_loop(self):
        prev_brightness = None
        while True:
            with self.lock:
                data = self.latest_frame
            if data and cv2 is not None and np is not None:
                arr = np.frombuffer(data, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
                brightness = img.mean()
                if prev_brightness is not None:
                    if brightness - prev_brightness > 40:
                        self._notify_alert("bright")
                    # laser dot detection - naive implementation
                    _, thresh = cv2.threshold(img, 250, 255, cv2.THRESH_BINARY)
                    if 0 < cv2.countNonZero(thresh) < 50:
                        self._notify_alert("laser")
                prev_brightness = brightness
            time.sleep(0.2)

    def _notify_alert(self, alert_type: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info("%s alert at %s", alert_type, timestamp)
        for q in self.analysis_subscribers:
            q.append({"type": alert_type, "time": timestamp})

    def get_frame(self):
        with self.lock:
            return self.latest_frame

    def update_config(self, **kwargs):
        with self.lock:
            self.recording = False
        for k, v in kwargs.items():
            if k in self.config:
                if k == "fps":
                    v = int(v)
                elif k in {"gain", "brightness"}:
                    v = float(v)
                elif k == "shutter":
                    v = int(v)
                elif k == "resolution" and isinstance(v, str):
                    w, h = v.split("x")
                    v = (int(w), int(h))
                self.config[k] = v
        self.apply_settings()

    def start_recording(self, with_preroll=False):
        if self.recording:
            return
        path = os.path.join(
            RECORDINGS_DIR,
            datetime.now().strftime("video_%Y%m%d_%H%M%S.mp4"),
        )
        fourcc = cv2.VideoWriter_fourcc(*"mp4v") if cv2 else 0
        self.video_writer = cv2.VideoWriter(
            path, fourcc, self.config["fps"], self.config["resolution"]
        ) if cv2 else None
        if with_preroll:
            for frame in list(self.frame_buffer):
                if self.video_writer:
                    self.video_writer.write(frame)
        self.recording = True

    def stop_recording(self):
        with self.lock:
            self.recording = False
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None


camera = CameraController()


def requires_auth(view_func):
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    wrapper.__name__ = view_func.__name__
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == PASSWORD:
            session["authed"] = True
            return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/")
@requires_auth
def index():
    return render_template(
        "index.html",
        gain=camera.config["gain"],
        shutter=camera.config["shutter"],
        fps=camera.config["fps"],
        brightness=camera.config["brightness"],
        resolution="%dx%d" % camera.config["resolution"],
    )


@app.route("/stream")
@requires_auth
def stream():
    def gen():
        while True:
            frame = camera.get_frame()
            if frame:
                yield (
                    b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(1 / camera.config["fps"])

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/control", methods=["POST"])
@requires_auth
def control():
    data = request.form.to_dict()
    camera.update_config(**data)
    return "", 204


@app.route("/snapshot")
@requires_auth
def snapshot():
    frame = camera.get_frame()
    if not frame:
        return "No frame", 500
    ts = datetime.now().strftime("image_%Y%m%d_%H%M%S.jpg")
    path = os.path.join(RECORDINGS_DIR, ts)
    with open(path, "wb") as f:
        f.write(frame)
    return Response(frame, mimetype="image/jpeg")


@app.route("/record", methods=["POST"])
@requires_auth
def record():
    action = request.form.get("action")
    if action == "start":
        preroll = request.form.get("preroll") == "1"
        camera.start_recording(with_preroll=preroll)
    elif action == "stop":
        camera.stop_recording()
    return "", 204


@app.route("/toggle-screen", methods=["POST"])
@requires_auth
def toggle_screen():
    path = "/sys/class/backlight/rpi_backlight/bl_power"
    try:
        with open(path, "r") as f:
            state = f.read().strip()
        new_state = "0" if state == "1" else "1"
        os.system(f"echo {new_state} | sudo tee {path} > /dev/null")
    except Exception as e:  # noqa: E722
        logging.error("Failed to toggle screen: %s", e)
        return "error", 500
    return "", 204


@app.route("/events")
@requires_auth
def events():
    q = deque()
    camera.analysis_subscribers.append(q)

    def stream_events():
        try:
            while True:
                if q:
                    event = q.popleft()
                    yield f"data: {event['type']} {event['time']}\n\n"
                time.sleep(0.5)
        finally:
            camera.analysis_subscribers.remove(q)

    return Response(stream_events(), mimetype="text/event-stream")


@app.route("/logout")
@requires_auth
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=5000)
