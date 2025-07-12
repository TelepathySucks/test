import subprocess

class TouchscreenControl:
    @staticmethod
    def set_display_power(state: str):
        """
        Toggle screen video output without affecting touch input.
        :param state: 'on' or 'off'
        """
        if state == 'off':
            subprocess.run(['vcgencmd', 'display_power', '0'])
        elif state == 'on':
            subprocess.run(['vcgencmd', 'display_power', '1'])
