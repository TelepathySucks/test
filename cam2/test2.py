from flask import Flask, Response
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
import io

app = Flask(__name__)
picam2 = Picamera2()

# Choose resolution, frame rate, and sensor mode
video_config = picam2.create_video_configuration(
    main={"size": (1280, 720), "format": "RGB888"},
    controls={
        "FrameDurationLimits": (33333, 33333),  # ~30 FPS
        "AnalogueGain": 16.0,                   # High gain for low light
        "ExposureTime": 20000                   # In microseconds (20 ms)
    }
)

picam2.configure(video_config)

# Output to in-memory buffer
output = io.BytesIO()
encoder = MJPEGEncoder()

picam2.start_recording(encoder, FileOutput(output))
picam2.start()

@app.route('/')
def index():
    return '<h2>Raspberry Pi HQ Camera Stream</h2><img src="/stream">'

@app.route('/stream')
def stream():
    def generate():
        while True:
            frame = output.getvalue()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                output.seek(0)
                output.truncate()
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
