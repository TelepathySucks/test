from flask import Flask, Response, render_template_string, request from picamera2 import Picamera2 import threading import time import cv2 import os import glob

app = Flask(name) picam2 = Picamera2()

Initial camera config

current_config = { "resolution": (1280, 720), "gain": 16.0, "shutter": 20000, "fps": 30, "color_mode": "normal" }

Camera safety lock

camera_lock = threading.Lock()

Updated function with manual control enforcement

def apply_camera_settings(): frame_duration = int(1_000_000 / current_config["fps"]) config = picam2.create_video_configuration( main={"size": current_config["resolution"]}, controls={ "FrameDurationLimits": (frame_duration, frame_duration), "AnalogueGain": current_config["gain"], "ExposureTime": current_config["shutter"], "AeEnable": False, "AwbEnable": False, "ColourCorrectionMatrix": [1.0]*9  # Optional: neutral matrix } ) with camera_lock: picam2.configure(config)

frame_lock = threading.Lock() latest_frame = None

Processing pipeline

def process_frame(frame): if current_config["color_mode"] == "gray": return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) elif current_config["color_mode"] == "heatmap": gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) return cv2.applyColorMap(gray, cv2.COLORMAP_JET) else: return frame

def capture_frames(): global latest_frame picam2.start() while True: with camera_lock: frame = picam2.capture_array() processed = process_frame(frame) ret, jpeg = cv2.imencode(".jpg", processed) if ret: with frame_lock: latest_frame = jpeg.tobytes() time.sleep(0.01)

@app.route('/') def index(): return render_template_string('''

<!DOCTYPE html><html>
<head>
    <title>Pi HQ Camera Stream</title>
    <style>
        body { margin: 0; background: black; color: white; font-family: sans-serif; overflow: hidden; }
        #stream { width: 100vw; height: auto; display: block; }
        #controls {
            position: absolute; top: 10px; left: 10px;
            background: rgba(0,0,0,0.7); padding: 10px; border-radius: 8px;
        }
        input[type=range], select { width: 100%; }
        button { margin-top: 5px; width: 100%; }
    </style>
</head>
<body>
    <img id="stream" src="/stream">
    <div id="controls">
        <label>Gain: <input type="range" min="1" max="32" step="0.1" value="{{ gain }}" oninput="update('gain', this.value)"></label><br>
        <label>Shutter (µs): <input type="range" min="100" max="1000000" step="100" value="{{ shutter }}" oninput="update('shutter', this.value)"></label><br>
        <label>FPS: <input type="range" min="1" max="60" value="{{ fps }}" oninput="update('fps', this.value)"></label><br>
        <label>Resolution:
            <select onchange="update('resolution', this.value)">
                <option value="640x480">640x480</option>
                <option value="1280x720" selected>1280x720</option>
                <option value="1920x1080">1920x1080</option>
                <option value="2028x1080">2028x1080 (binned)</option>
            </select>
        </label><br>
        <label>Color Mode:
            <select onchange="update('color_mode', this.value)">
                <option value="normal">Normal</option>
                <option value="gray">Grayscale</option>
                <option value="heatmap">Heatmap</option>
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
    ''', gain=current_config["gain"], shutter=current_config["shutter"], fps=current_config["fps"])@app.route('/stream') def stream(): def generate(): while True: with frame_lock: frame = latest_frame if frame: yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n') time.sleep(0.03) return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/control', methods=['POST']) def control(): global current_config data = request.form if 'gain' in data: current_config["gain"] = float(data['gain']) if 'shutter' in data: current_config["shutter"] = int(data['shutter']) if 'fps' in data: current_config["fps"] = int(data['fps']) if 'resolution' in data: w, h = map(int, data['resolution'].split('x')) current_config["resolution"] = (w, h) if 'color_mode' in data: current_config["color_mode"] = data['color_mode']

with camera_lock:
    picam2.stop()
    apply_camera_settings()
    picam2.start()
return ('', 204)

@app.route('/toggle-screen', methods=['POST']) def toggle_screen(): try: base_path = "/sys/class/backlight/" candidates = glob.glob(base_path + "*/bl_power") if candidates: backlight_path = candidates[0] with open(backlight_path, "r") as f: current = f.read().strip() new_state = '0' if current == '1' else '1' os.system(f"echo {new_state} | sudo tee {backlight_path}") else: print("No valid backlight device found") except Exception as e: print("Backlight toggle failed:", e) return ('', 204)

if name == 'main': apply_camera_settings() threading.Thread(target=capture_frames, daemon=True).start() app.run(host='0.0.0.0', port=5000, debug=False)

