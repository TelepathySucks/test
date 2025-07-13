"""Utilities for controlling the Raspberry Pi touchscreen backlight."""

import subprocess


class TouchscreenControl:
    """Wrapper around ``vcgencmd display_power``."""

    @staticmethod
    def set_display_power(state: str) -> None:
        """Turn the display video output on or off."""
        if state == 'off':
            subprocess.run(['vcgencmd', 'display_power', '0'], check=False)
        elif state == 'on':
            subprocess.run(['vcgencmd', 'display_power', '1'], check=False)
