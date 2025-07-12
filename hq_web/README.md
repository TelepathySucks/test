# Raspberry Pi HQ Camera Web Controller

This Flask-based application streams the IMX477 HQ camera and provides controls for exposure, gain, frame rate and resolution. It includes basic light event detection and the ability to capture snapshots and start/stop recording with an optional pre-roll buffer.

## Setup

Install dependencies (requires Python 3.9+ and Raspberry Pi OS 64-bit):

```bash
pip install -r requirements.txt
```

Run the application:

```bash
python app.py
```

The server listens on port `5000` by default.
