"""Flask web server exposing the surveillance UI and API."""

import datetime
import subprocess
import threading
import time

import cv2
from flask import Flask, render_template_string, Response, request, jsonify
from main_controller import MainController

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
        'colour_gains': [1.0, 1.0],
        'brightness': 0,
        'contrast': 0,
        'saturation': 0,
        'sharpness': 0,
        'denoise': 0,
        'awb': False,
        'ae': False,
        'agc': False,
        'demosaic': 'on'
    },
    'buffer': {
        'length': 5,
        'memory': 0
    }
}

controller = MainController(config)

event_log: list[str] = []
event_log_lock = threading.Lock()

# Register callback and start the main controller after defining logging helper

def get_cpu_temp():
    """Return the CPU temperature in Celsius or ``None`` if unavailable."""
    try:
        output = subprocess.check_output(['vcgencmd', 'measure_temp'], text=True)
        return float(output.split('=')[1].split("'")[0])
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError, ValueError):
        return None

# ---- Event Logging ----
def log_event(kind):
    """Append a detection event to the rolling log."""
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    with event_log_lock:
        event_log.append(f"{timestamp} - {kind}")
        if len(event_log) > 10:
            event_log.pop(0)

controller.set_trigger_callback(log_event)
controller.start()

# ---- Web Interface ----
@app.route('/')
def index():
    """Serve the main HTML interface."""
    with open("web_template.html", encoding="utf-8") as f:
        html = f.read()
    return render_template_string(html)

@app.route('/stream')
def stream():
    """Stream JPEG frames from the camera as multipart data."""
    def generate():
        while True:
            frame = controller.get_last_frame()
            if frame is not None:
                _, buffer = cv2.imencode('.jpg', frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.1)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ---- API Routes ----
@app.route('/get_config')
def get_config():
    """Return the current runtime configuration as JSON."""
    with event_log_lock:
        log_copy = list(event_log)

    return jsonify({
        'detection': config['detection'],
        'camera': {
            **config['camera'],
            'resolution': f"{config['camera']['resolution'][0]}x{config['camera']['resolution'][1]}"
        },
        'buffer': {
            **config['buffer'],
            'memory_usage': controller.buffer.estimate_memory_usage()
        },
        'log': log_copy,
        'cpu_temp': get_cpu_temp()
    })

@app.route('/update_config', methods=['POST'])
def update_config():
    """Update detection or camera settings from the client."""
    data = request.json or {}
    config['detection'].update(data.get('detection', {}))

    cam_data = data.get('camera', {})
    if 'resolution' in cam_data:
        res = cam_data['resolution']
        if isinstance(res, str) and 'x' in res:
            cam_data['resolution'] = tuple(int(x) for x in res.split('x'))

    reconfig_needed = False
    for key, val in cam_data.items():
        if config['camera'].get(key) != val:
            config['camera'][key] = val
            reconfig_needed = True

    buffer_data = data.get('buffer', {})
    if 'length' in buffer_data and buffer_data['length'] != config['buffer'].get('length'):
        config['buffer']['length'] = buffer_data['length']
        controller.buffer.update_config(length=buffer_data['length'])

    if reconfig_needed:
        controller.reconfigure_camera(config['camera'])

    return jsonify({'status': 'updated'})

@app.route('/save_buffer', methods=['POST'])
def save_buffer():
    """Persist the current buffer to disk."""
    controller.buffer.save_to_file()
    log_event("Manual Save")
    return jsonify({'status': 'buffer saved'})

@app.route('/toggle_screen', methods=['POST'])
def toggle_screen():
    """Turn the attached touchscreen display on or off."""
    action = request.json.get('state')
    from touchscreen_control import TouchscreenControl
    if action == 'off':
        TouchscreenControl.set_display_power('off')
    elif action == 'on':
        TouchscreenControl.set_display_power('on')
    return jsonify({'status': f'screen turned {action}'})

# ---- Start Server ----
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
