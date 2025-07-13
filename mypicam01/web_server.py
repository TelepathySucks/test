"""Flask web interface for the surveillance system."""

import datetime
import subprocess
import time
from collections import deque
from threading import Lock, Thread

import cv2
from flask import Flask, Response, jsonify
from flask import render_template_string, request
from main_controller import MainController
from flash_detector import FlashDetector
from laser_detector import LaserDetector
from frame_buffer import FrameBuffer

app = Flask(__name__)

# ---- System Configuration and Controller Setup ----
config = {
    'detection': {
        'flash_threshold': 5.0,
        'laser_threshold': 20,
        'min_blob': 5,
        'max_blob': 50,
        'autosave_flash': True,
        'autosave_laser': True,
        'sound_flash': True,
        'sound_laser': True
    },
    'camera': {
        'resolution': (640, 480),
        'fps': 10,
        'exposure': 10000,
        'gain': 2.0,
        'demosaic': 'on'
    },
    'buffer': {
        'length': 5,
        'memory': 0
    }
}

controller = MainController(config)

event_log = deque(maxlen=10)
log_lock = Lock()

# ---- Event Logging ----


def log_event(kind):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    with log_lock:
        event_log.append(f"{timestamp} - {kind}")


controller.set_trigger_callback(lambda msg: log_event(msg))
controller.start()

# ---- Web Interface ----


@app.route('/')
def index():
    with open("web_template.html", "r", encoding="utf-8") as f:
        html = f.read()
    return render_template_string(html)


@app.route('/stream')
def stream():
    def generate():
        while True:
            frame = controller.get_last_frame()
            if frame is not None:
                _, buffer_jpg = cv2.imencode(".jpg", frame)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + buffer_jpg.tobytes()
                    + b"\r\n"
                )
            time.sleep(0.1)
    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ---- API Routes ----

@app.route('/get_config')
def get_config():
    with log_lock:
        logs = list(event_log)
    return jsonify(
        {
            "detection": config["detection"],
            "camera": config["camera"],
            "buffer": config["buffer"],
            "log": logs,
        }
    )


@app.route('/update_config', methods=['POST'])
def update_config():
    data = request.json
    config['detection'].update(data.get('detection', {}))
    config['camera'].update(data.get('camera', {}))
    config['buffer'].update(data.get('buffer', {}))

    controller.flash_detector = FlashDetector(config['detection'])
    controller.laser_detector = LaserDetector(config['detection'])
    controller.buffer = FrameBuffer(config['buffer'])

    if 'camera' in data:
        controller.reconfigure_camera(config['camera'])

    return jsonify({'status': 'updated'})


@app.route('/save_buffer', methods=['POST'])
def save_buffer():
    Thread(target=controller.buffer.save_to_file).start()
    log_event("Manual Save")
    return jsonify({'status': 'buffer saved'})


@app.route('/toggle_screen', methods=['POST'])
def toggle_screen():
    action = request.json.get('state')
    cmd = ["vcgencmd", "display_power", "1" if action == "on" else "0"]
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return jsonify({'status': f'screen turned {action}'})


# ---- Start Server ----
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
