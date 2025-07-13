"""Camera initialization utilities."""

from picamera2 import Picamera2

class CameraInitializer:
    """Helper to apply configuration options to the camera."""

    def __init__(self, config):
        """Create the initializer with a configuration dict."""
        self.config = config
        self.picam2 = Picamera2()

    def apply_config(self):
        """Apply the stored configuration to the underlying camera."""
        controls = {
            "FrameDurationLimits": (
                int(1e6 / self.config['fps']),
                int(1e6 / self.config['fps'])
            ),
            "AnalogueGain": self.config['gain'],
            "ExposureTime": self.config['exposure'],
            "AwbEnable": False,
            "AeEnable": False,
            "NoiseReductionMode": 0,  # Off
            "Sharpness": self.config.get("sharpness", 0),
            "Contrast": self.config.get("contrast", 0),
            "Saturation": self.config.get("saturation", 0),
            "Brightness": self.config.get("brightness", 0),
        }

        if "colour_gains" in self.config:
            controls["ColourGains"] = self.config["colour_gains"]

        if "denoise" in self.config:
            controls["NoiseReductionStrength"] = self.config["denoise"]

        if self.config.get("demosaic") == "off":
            self.picam2.configure(self.picam2.create_video_configuration(
                main={"size": self.config["resolution"], "format": "RGB888"},
                transform=None,
                raw=True
            ))
        else:
            self.picam2.configure(self.picam2.create_video_configuration(
                main={"size": self.config["resolution"], "format": "RGB888"},
                transform=None,
                controls=controls
            ))

        self.picam2.set_controls(controls)

    def get_camera(self):
        """Return the configured ``Picamera2`` instance."""
        return self.picam2
