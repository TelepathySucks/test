from flask import Flask, Response
from picamera2 import Picamera2
import threading
import time
import cv2

app = Flask(__name__)
picam2 = Picamera2()

# Configure camera with resolution, shutter, gain, and framerate
config = picam2.create_video_configuration(
    main={"size": (1280, 720)},
    controls={
        "FrameDurationLimits": (33333, 33333),  # 30 FPS
        "AnalogueGain": 16.0,
        "ExposureTime": 20000  # microseconds
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
        time.sleep(0.01)  # reduce CPU usage

@app.route('/')
def index():
    return '<h2>Raspberry Pi HQ Camera Stream</h2><img src="/stream">'

@app.route('/stream')
def stream():
    def generate():
        while True:
            with frame_lock:
                frame = latest_frame
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.03)  # ~30 FPS
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    threading.Thread(target=capture_frames, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)
