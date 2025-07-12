import os
import io
import threading
import time
from datetime import datetime, timedelta
from collections import deque

from flask import Flask, Response, request, redirect, url_for, session, render_template_string, send_from_directory

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder, H264Encoder
from picamera2.outputs import FileOutput
import cv2

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-me')
PASSWORD = os.environ.get('CAMERA_PASSWORD', 'raspberry')

MEDIA_DIR = os.path.join(os.path.dirname(__file__), 'media')
os.makedirs(MEDIA_DIR, exist_ok=True)

picam2 = Picamera2()

current_config = {
    'resolution': (640, 480),
    'gain': 1.0,
    'shutter': 1000,  # microseconds
    'brightness': 0,
    'fps': 30
}

alert_state = {
    'bright_room': False,
    'laser_dot': False,
    'record_on_alert': False
}

recording = False
record_lock = threading.Lock()
record_writer = None
preroll_buffer = deque(maxlen=60)  # ~2s at 30 fps

frame_lock = threading.Lock()
latest_frame = b''

log_lock = threading.Lock()
log_file = os.path.join(MEDIA_DIR, 'events.log')


def log_event(message: str):
    timestamp = datetime.now().isoformat()
    line = f"{timestamp} - {message}\n"
    with log_lock:
        with open(log_file, 'a') as f:
            f.write(line)


def apply_camera_settings():
    frame_duration = int(1_000_000 / current_config['fps'])
    if current_config['shutter'] > frame_duration:
        current_config['shutter'] = frame_duration
    config = picam2.create_video_configuration(
        main={'size': current_config['resolution']},
        controls={
            'FrameDurationLimits': (frame_duration, frame_duration),
            'AnalogueGain': current_config['gain'],
            'ExposureTime': current_config['shutter'],
            'Brightness': current_config['brightness']
        }
    )
    picam2.configure(config)


def start_camera():
    try:
        picam2.start()
    except Exception:
        picam2.stop()
        picam2.start()


def capture_thread():
    global latest_frame, recording, record_writer
    start_camera()
    encoder = MJPEGEncoder()
    picam2.start_recording(encoder, FileOutput())
    while True:
        frame = picam2.capture_array()
        ret, jpeg = cv2.imencode('.jpg', frame)
        if ret:
            with frame_lock:
                latest_frame = jpeg.tobytes()
            with record_lock:
                if recording and record_writer is not None:
                    record_writer.write(frame)
            preroll_buffer.append(frame)
            check_alerts(frame)
        time.sleep(1 / current_config['fps'])


def check_alerts(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    avg = gray.mean()
    if alert_state['bright_room'] and avg > 200:
        log_event('Bright room alert')
    if alert_state['laser_dot']:
        _, thresh = cv2.threshold(gray, 250, 255, cv2.THRESH_BINARY)
        if cv2.countNonZero(thresh) < 10:
            return
        log_event('Laser dot alert')
        if alert_state['record_on_alert'] and not recording:
            start_recording()


def start_recording():
    global recording, record_writer
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(MEDIA_DIR, f'{ts}.mp4')
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    record_writer = cv2.VideoWriter(path, fourcc, current_config['fps'], current_config['resolution'])
    # Write preroll frames
    for f in list(preroll_buffer):
        record_writer.write(f)
    recording = True
    log_event(f'Start recording {path}')


def stop_recording():
    global recording, record_writer
    with record_lock:
        if record_writer:
            record_writer.release()
        recording = False
        record_writer = None
    log_event('Stop recording')


def save_snapshot():
    with frame_lock:
        data = latest_frame
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(MEDIA_DIR, f'{ts}.jpg')
    with open(path, 'wb') as f:
        f.write(data)
    log_event(f'Snapshot saved {path}')
    return path


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == PASSWORD:
            session['auth'] = True
            return redirect(url_for('index'))
    return render_template_string('''
    <form method="post" style="margin-top:30vh;text-align:center;color:white;background:black;height:100vh">
        <input type="password" name="password" placeholder="Password">
        <button type="submit">Login</button>
    </form>''')


def login_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get('auth'):
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper


@app.route('/')
@login_required
def index():
    return render_template_string(PAGE_TEMPLATE,
                                  gain=current_config['gain'],
                                  shutter=current_config['shutter'],
                                  brightness=current_config['brightness'],
                                  fps=current_config['fps'],
                                  res=f"{current_config['resolution'][0]}x{current_config['resolution'][1]}",
                                  alerts=alert_state,
                                  recording=recording)


@app.route('/stream')
@login_required
def stream():
    def gen():
        while True:
            with frame_lock:
                frame = latest_frame
            if frame:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.01)
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/control', methods=['POST'])
@login_required
def control():
    global current_config
    data = request.json or {}
    update_fps = False
    if 'gain' in data:
        current_config['gain'] = float(data['gain'])
    if 'shutter' in data:
        current_config['shutter'] = int(data['shutter'])
    if 'brightness' in data:
        current_config['brightness'] = int(data['brightness'])
    if 'fps' in data:
        current_config['fps'] = int(data['fps'])
        update_fps = True
    if 'resolution' in data:
        w, h = map(int, data['resolution'].split('x'))
        current_config['resolution'] = (w, h)
    picam2.pause()
    apply_camera_settings()
    picam2.resume()
    if update_fps:
        current_config['shutter'] = int(1_000_000 / current_config['fps'])
    return {'status': 'ok', 'config': current_config}


@app.route('/snapshot')
@login_required
def snapshot():
    path = save_snapshot()
    return send_from_directory(MEDIA_DIR, os.path.basename(path))


@app.route('/record', methods=['POST'])
@login_required
def record():
    action = request.json.get('action')
    if action == 'start' and not recording:
        start_recording()
    elif action == 'stop' and recording:
        stop_recording()
    return {'recording': recording}


@app.route('/alerts', methods=['POST'])
@login_required
def alerts():
    data = request.json
    for k in ['bright_room', 'laser_dot', 'record_on_alert']:
        if k in data:
            alert_state[k] = bool(data[k])
    return alert_state


@app.route('/toggle_screen', methods=['POST'])
@login_required
def toggle_screen():
    backlight_path = '/sys/class/backlight/rpi_backlight/bl_power'
    try:
        with open(backlight_path, 'r') as f:
            current = f.read().strip()
        new_state = '0' if current == '1' else '1'
        os.system(f'echo {new_state} | sudo tee {backlight_path} > /dev/null')
    except Exception as e:
        log_event(f'Screen toggle failed: {e}')
    return {'status': 'ok'}


@app.route('/media/<path:name>')
@login_required
def media(name):
    return send_from_directory(MEDIA_DIR, name)


PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
body { background: #111; color: white; font-family: sans-serif; margin:0; }
#stream { width: 100%; height: auto; }
.controls { padding:10px; }
input, select { width:100%; margin-bottom:5px; }
button { width:100%; margin-top:5px; }
</style>
</head>
<body>
<img id='stream' src='/stream' onclick="toggleFull()">
<div class='controls'>
<label>Gain <input type='range' min='1' max='32' step='0.1' value='{{ gain }}' id='gain'></label>
<label>Shutter µs <input type='number' min='10' max='1000000' value='{{ shutter }}' id='shutter'></label>
<label>Brightness <input type='range' min='-1' max='1' step='0.1' value='{{ brightness }}' id='brightness'></label>
<label>FPS <input type='number' min='1' max='60' value='{{ fps }}' id='fps'></label>
<select id='res'>
<option value='640x480' {% if res=='640x480' %}selected{% endif %}>640x480</option>
<option value='1280x720' {% if res=='1280x720' %}selected{% endif %}>1280x720</option>
<option value='1920x1080' {% if res=='1920x1080' %}selected{% endif %}>1920x1080</option>
<option value='2028x1080' {% if res=='2028x1080' %}selected{% endif %}>2028x1080 (binned)</option>
</select>
<button onclick='update()'>Apply</button>
<button onclick='snap()'>Snapshot</button>
<button onclick='record()'>{{ "Stop" if recording else "Record" }}</button>
<label><input type='checkbox' id='bright' {% if alerts['bright_room'] %}checked{% endif %}> Bright Room Alert</label>
<label><input type='checkbox' id='laser' {% if alerts['laser_dot'] %}checked{% endif %}> Laser Dot Alert</label>
<label><input type='checkbox' id='rec_alert' {% if alerts['record_on_alert'] %}checked{% endif %}> Record on Alert</label>
<button onclick='toggleScreen()'>Toggle Screen</button>
</div>
<script>
function update(){
fetch('/control', {method:'POST', headers:{'Content-Type':'application/json'},
body:JSON.stringify({gain:gain.value, shutter:shutter.value, brightness:brightness.value, fps:fps.value, resolution:res.value})})}
function snap(){window.location='/snapshot'}
function record(){
let action = this.innerText=='Record'?'start':'stop';
fetch('/record', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:action})}).then(()=>location.reload())
}
function toggleFull(){ if(document.fullscreenElement){document.exitFullscreen()}else{stream.requestFullscreen()} }
function toggleScreen(){fetch('/toggle_screen',{method:'POST'})}
['bright','laser','rec_alert'].forEach(id=>{document.getElementById(id).onchange=()=>{
fetch('/alerts',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({[id==='bright'?'bright_room':id==='laser'?'laser_dot':'record_on_alert']:document.getElementById(id).checked})})})
})
</script>
</body>
</html>
"""


if __name__ == '__main__':
    apply_camera_settings()
    t = threading.Thread(target=capture_thread, daemon=True)
    t.start()
    log_event('Server started')
    app.run(host='0.0.0.0', port=5000)
