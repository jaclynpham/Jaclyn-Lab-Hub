"""Warm the LED strip as someone comes close to the hugging sculpture.

The Qwiic VCNL4040 reports a larger number as a person gets closer. Far away
the WS2812B strip is a pale orange. Up close it is a deep warm orange.
The hue stays orange. What changes is the saturation.

Wiring
  Qwiic cable from the Pi to the VCNL4040. That uses I2C, GPIO 2 and GPIO 3.
  Strip data wire to a free GPIO. This script uses GPIO 18 unless you pass
  --pin. Do not use GPIO 2 or 3 for the strip.
  Strip 5 V to a 5 V supply that can feed the whole strip. A long strip
  should not take its power from the Pi. Connect the strip ground to the
  Pi ground.

Start with nothing in front of the sensor. The first second is the far
reading. Move closer and the orange should deepen. If it barely changes,
print the numbers and pass a smaller --span.

  python hug.py
  python hug.py --leds 60 --pin 18
"""

import argparse
import colorsys
import sys
import time


LIGHT_HUE = 32.0 / 360.0
WARM_HUE = 18.0 / 360.0
LIGHT_SATURATION = 0.18
WARM_SATURATION = 1.0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Pale orange far away, warm orange up close.",
    )
    parser.add_argument("--pin", type=int, default=18, help="GPIO for the strip data wire (default 18)")
    parser.add_argument("--leds", type=int, default=30, help="number of LEDs on the strip (default 30)")
    parser.add_argument("--brightness", type=float, default=0.45, help="strip brightness, 0 to 1 (default 0.45)")
    parser.add_argument("--span", type=float, default=1500.0, help="proximity rise from far to fully warm (default 1500)")
    args = parser.parse_args()
    if args.leds < 1:
        raise SystemExit("--leds must be at least 1.")
    if not 0.0 < args.brightness <= 1.0:
        raise SystemExit("--brightness must be above 0 and at most 1.")
    if args.span <= 0:
        raise SystemExit("--span must be greater than 0.")
    return args


def open_sensor():
    try:
        import qwiic_proximity
    except ImportError as exc:
        raise SystemExit(
            "sparkfun-qwiic-proximity is not installed for this Python.\n"
            "  python -m pip install sparkfun-qwiic-proximity"
        ) from exc
    sensor = qwiic_proximity.QwiicProximity()
    if not sensor.connected:
        raise SystemExit(
            "The VCNL4040 is not on the Qwiic bus.\n"
            "Check the cable. i2cdetect -y 1 should show 60."
        )
    sensor.begin()
    return sensor


def board_model():
    try:
        with open("/proc/device-tree/model", encoding="ascii", errors="replace") as handle:
            return handle.read().replace("\x00", "").strip()
    except OSError:
        return "unknown"


class Strip:
    """Same fill/show shape as the other scripts, backed by rpi_ws281x."""

    def __init__(self, strip, color):
        self._strip = strip
        self._color = color
        self.byteorder = "GRB"

    def fill(self, rgb):
        red, green, blue = rgb
        if self.byteorder == "RGB":
            red, green = green, red
        packed = self._color(red, green, blue)
        for index in range(self._strip.numPixels()):
            self._strip.setPixelColor(index, packed)

    def show(self):
        self._strip.show()


def open_strip(pin_number, count, brightness):
    import os

    model = board_model()
    print(f"Board: {model}")
    if "Pi 5" in model:
        return open_pi5_strip(pin_number, count, brightness)
    if os.geteuid() != 0:
        print("Not running as root. GPIO 18's LED signal needs sudo, or the pin stays still.")
        print("  sudo .venv/bin/python led_test.py --color 255 0 0")
    try:
        from rpi_ws281x import Adafruit_NeoPixel, Color
    except ImportError as exc:
        raise SystemExit(
            "rpi_ws281x is not installed for this Python.\n"
            "  .venv/bin/pip install rpi_ws281x"
        ) from exc
    level = max(1, min(255, int(round(brightness * 255))))
    channel = 1 if pin_number in (13, 19, 41, 45, 53) else 0
    strip = Adafruit_NeoPixel(count, pin_number, 800000, 10, False, level, channel)
    try:
        strip.begin()
    except Exception as exc:
        raise SystemExit(
            f"Could not start the LED signal on GPIO {pin_number}.\n"
            "Run with sudo. Data goes to physical pin 12 for GPIO 18, and the strip's arrow points away from the Pi.\n"
            "The strip ground and the Pi ground have to be the same wire.\n"
            f"({exc})"
        ) from exc
    print(f"LED signal started on GPIO {pin_number}, {count} LEDs, brightness {level}/255.")
    return Strip(strip, Color)


def open_pi5_strip(pin_number, count, brightness):
    import os

    if not os.path.exists("/dev/pio0"):
        raise SystemExit(
            "This Pi 5 cannot drive the strip yet: /dev/pio0 is missing.\n"
            "Update the board, then reboot:\n"
            "  sudo apt update && sudo apt full-upgrade && sudo reboot"
        )
    try:
        import board
        import adafruit_pixelbuf
        from adafruit_raspberry_pi5_neopixel_write import neopixel_write
    except ImportError as exc:
        raise SystemExit(
            "The Pi 5 LED driver is not installed in this virtual environment.\n"
            "  venv/bin/pip install Adafruit-Blinka adafruit-circuitpython-pixelbuf Adafruit-Blinka-Raspberry-Pi5-Neopixel"
        ) from exc
    pin = getattr(board, f"D{pin_number}", None)
    if pin is None:
        raise SystemExit(f"GPIO {pin_number} is not a pin this board library knows.")

    class Pi5Strip(adafruit_pixelbuf.PixelBuf):
        def __init__(self):
            self._pin = pin
            super().__init__(size=count, byteorder="GRB", brightness=brightness, auto_write=False)

        def _transmit(self, buffer):
            neopixel_write(self._pin, buffer)

    print(f"Pi 5 LED signal on GPIO {pin_number}, {count} LEDs.")
    print("rpi_ws281x cannot run on this board. That was the earlier crash, not the wiring.")
    return Pi5Strip()


def rest_level(sensor):
    print("Leave the space in front of the sensor empty.")
    samples = []
    for _ in range(8):
        samples.append(float(sensor.get_proximity()))
        time.sleep(0.05)
    return max(samples)


def closeness(proximity, floor, span):
    return min(1.0, max(0.0, (proximity - floor) / span))


def orange(amount):
    hue = LIGHT_HUE + (WARM_HUE - LIGHT_HUE) * amount
    saturation = LIGHT_SATURATION + (WARM_SATURATION - LIGHT_SATURATION) * amount
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, 1.0)
    return (int(red * 255), int(green * 255), int(blue * 255))


def lights_off(strip):
    strip.fill((0, 0, 0))
    strip.show()


def main():
    args = parse_args()
    sensor = open_sensor()
    strip = open_strip(args.pin, args.leds, args.brightness)
    floor = rest_level(sensor)
    print(
        f"Far reading {floor:.0f}. "
        f"Fully warm orange is about {floor + args.span:.0f}. "
        f"Strip: {args.leds} LEDs on GPIO {args.pin}."
    )
    smooth = floor
    shown = None
    try:
        while True:
            reading = float(sensor.get_proximity())
            smooth = smooth * 0.75 + reading * 0.25
            amount = closeness(smooth, floor, args.span)
            color = orange(amount)
            if color != shown:
                strip.fill(color)
                strip.show()
                shown = color
            print(
                f"proximity {smooth:.0f}   warmth {amount * 100:.0f}%   "
                f"rgb {color[0]} {color[1]} {color[2]}"
            )
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nLights off.")
    finally:
        lights_off(strip)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
