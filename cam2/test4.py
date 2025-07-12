from flask import Flask, Response, render_template_string, request
from picamera2 import Picamera2
import threading
import time
import cv2
import os

app = Flask(__name__)
picam2 = Picamera2()

# Initial camera config
current_config = {
    "resolution": (1280, 720),
    "gain": 16.0,
    "shutter": 20000,  # in microseconds
    "fps": 30
}

def apply_camera_settings():
    frame_duration = int(1_000_000 / current_config["fps"])
    config = picam2.create_video_configuration(
        main={"size": current_config["resolution"]},
        controls={
            "FrameDurationLimits": (frame_duration, frame_duration),
            "AnalogueGain": current_config["gain"],
            "ExposureTime": current_config["shutter"]
        }
    )
    picam2.configure(config)

frame_lock = threading.Lock()
latest_frame = None

def capture_frames():
    global latest_frame
    picam2.start()
    while True:
        frame = picam2.capture_array()
        ret, jpeg = cv2.imencode(".jpg", frame)
        if ret:
            with frame_lock:
                latest_frame = jpeg.tobytes()
        time.sleep(0.01)

@app.route('/')
def index():
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>Pi HQ Camera Stream</title>
    <style>
        body {
            margin: 0;
            background: black;
            color: white;
            font-family: sans-serif;
            overflow: hidden;
        }
        #stream {
            width: 100vw;
            height: auto;
            display: block;
        }
        #controls {
            position: absolute;
            top: 10px;
            left: 10px;
            background: rgba(0,0,0,0.7);
            padding: 10px;
            border-radius: 8px;
        }
        input[type=range], select {
            width: 100%;
        }
        button {
            margin-top: 5px;
            width: 100%;
        }
    </style>
</head>
<body>
    <img id="stream" src="/stream">
    <div id="controls">
        <label>Gain: <input type="range" min="1" max="32" step="0.1" value="{{ gain }}" 
               oninput="update('gain', this.value)"></label><br>
        <label>Shutter (µs): <input type="range" min="100" max="1000000" step="100" value="{{ shutter }}" 
               oninput="update('shutter', this.value)"></label><br>
        <label>FPS: <input type="range" min="1" max="60" value="{{ fps }}" 
               oninput="update('fps', this.value)"></label><br>
        <label>Resolution: 
            <select onchange="update('resolution', this.value)">
                <option value="640x480">640x480</option>
                <option value="1280x720" selected>1280x720</option>
                <option value="1920x1080">1920x1080</option>
                <option value="2028x1080">2028x1080 (binned)</option>
            </select>
        </label><br>
        <button onclick="toggleScreen()">Toggle Pi Screen</button>
    </div>

    <script>
        function update(key, val) {
            fetch('/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: key + '=' + val
            });
        }
        function toggleScreen() {
            fetch('/toggle-screen', {method: 'POST'});
        }
    </script>
</body>
</html>
    ''', gain=current_config["gain"], shutter=current_config["shutter"], fps=current_config["fps"])

@app.route('/stream')
def stream():
    def generate():
        while True:
            with frame_lock:
                frame = latest_frame
            if frame:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.03)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/control', methods=['POST'])
def control():
    global current_config
    data = request.form
    if 'gain' in data:
        current_config["gain"] = float(data['gain'])
    if 'shutter' in data:
        current_config["shutter"] = int(data['shutter'])
    if 'fps' in data:
        current_config["fps"] = int(data['fps'])
    if 'resolution' in data:
        w, h = map(int, data['resolution'].split('x'))
        current_config["resolution"] = (w, h)
    picam2.stop()
    apply_camera_settings()
    picam2.start()
    return ('', 204)

@app.route('/toggle-screen', methods=['POST'])
def toggle_screen():
    try:
        backlight_path = "/sys/class/backlight/rpi_backlight/bl_power"
        with open(backlight_path, "r") as f:
            current = f.read().strip()
        new_state = '0' if current == '1' else '1'
        os.system(f"echo {new_state} | sudo tee {backlight_path}")
    except Exception as e:
        print("Backlight toggle failed:", e)
    return ('', 204)

if __name__ == '__main__':
    apply_camera_settings()
    threading.Thread(target=capture_frames, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)
