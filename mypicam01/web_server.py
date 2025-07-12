from flask import Flask, render_template_string, Response, request, jsonify
import time, datetime, subprocess
import cv2
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
        'demosaic': 'on'
    },
    'buffer': {
        'length': 5,
        'memory': 0
    }
}

controller = MainController(config)
controller.set_trigger_callback(lambda msg: log_event(msg))
controller.start()

event_log = []

# ---- Event Logging ----
def log_event(kind):
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    event_log.append(f"{timestamp} - {kind}")
    if len(event_log) > 10:
        event_log.pop(0)

# ---- Web Interface ----
@app.route('/')
def index():
    html = open("web_template.html").read()
    return render_template_string(html)

@app.route('/stream')
def stream():
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
    return jsonify({
        'detection': config['detection'],
        'camera': config['camera'],
        'buffer': config['buffer'],
        'log': event_log
    })

@app.route('/update_config', methods=['POST'])
def update_config():
    data = request.json
    config['detection'].update(data.get('detection', {}))
    config['camera'].update(data.get('camera', {}))
    config['buffer'].update(data.get('buffer', {}))

    if 'camera' in data:
        controller.reconfigure_camera(config['camera'])

    return jsonify({'status': 'updated'})

@app.route('/save_buffer', methods=['POST'])
def save_buffer():
    controller.buffer.save_to_file()
    log_event("Manual Save")
    return jsonify({'status': 'buffer saved'})

@app.route('/toggle_screen', methods=['POST'])
def toggle_screen():
    action = request.json.get('state')
    if action == 'off':
        subprocess.run(['vcgencmd', 'display_power', '0'])
    elif action == 'on':
        subprocess.run(['vcgencmd', 'display_power', '1'])
    return jsonify({'status': f'screen turned {action}'})

# ---- Start Server ----
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
