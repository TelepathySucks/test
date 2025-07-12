# Raspberry Pi HQ Camera Web Controller

This project provides a Flask based web interface for the Raspberry Pi HQ
camera.  It streams MJPEG video, exposes controls for camera parameters and
allows snapshots and video recording directly from a browser.  Basic
password authentication is included so only one client at a time can control
the camera.

## Quick start

1. Install dependencies on the Raspberry Pi:

```bash
sudo apt install python3-flask python3-picamera2 python3-opencv
```

2. Run the application:

```bash
python3 hqapp/app.py
```

3. Open a browser on your phone or computer and navigate to
`http://<pi-address>:5000`.  Log in with the default password `raspberry`.

### Autostart on boot

Create a simple systemd service at `/etc/systemd/system/hqcam.service`:

```ini
[Unit]
Description=HQ Camera Web App
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/hqapp/app.py
WorkingDirectory=/path/to/hqapp
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable it with:

```bash
sudo systemctl enable hqcam.service
sudo systemctl start hqcam.service
```

The recordings and snapshots will be saved in `hqapp/recordings/` with
timestamped filenames.
