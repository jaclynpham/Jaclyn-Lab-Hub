"""Paint the whole WS2812B strip one color that you type.

On a Pi 5 this sends the color over SPI. The data wire is GPIO 10, physical pin 19.
Run it with sudo. A working strip becomes one flat color.

  sudo venv/bin/python led_test.py --color 255 0 0
  sudo venv/bin/python led_test.py

Then try 0 255 0 and 0 0 255. q turns the strip off.
"""

import argparse
import time

from hug import lights_off, open_strip


def parse_args():
    parser = argparse.ArgumentParser(description="Set every LED to one typed RGB color.")
    parser.add_argument("--pin", type=int, default=18, help="GPIO for the strip on older Pis (default 18). A Pi 5 uses GPIO 10.")
    parser.add_argument("--leds", type=int, default=30, help="number of LEDs on the strip (default 30)")
    parser.add_argument("--brightness", type=float, default=1.0, help="strip brightness, 0 to 1 (default 1)")
    parser.add_argument("--order", choices=("grb", "rgb"), default="grb", help="WS2812B color order (default grb)")
    parser.add_argument("--color", nargs=3, type=int, metavar=("R", "G", "B"), help="set this color and hold it")
    args = parser.parse_args()
    if args.leds < 1:
        raise SystemExit("--leds must be at least 1.")
    if not 0.0 < args.brightness <= 1.0:
        raise SystemExit("--brightness must be above 0 and at most 1.")
    return args


def ask_rgb():
    while True:
        typed = input("RGB 0-255 (example 255 76 0, q to quit): ").strip()
        if typed.lower() in ("q", "quit"):
            return None
        parts = typed.replace(",", " ").split()
        if len(parts) != 3:
            print("Type three numbers, like 255 76 0.")
            continue
        try:
            color = tuple(int(part) for part in parts)
        except ValueError:
            print("Use whole numbers from 0 to 255.")
            continue
        if any(channel < 0 or channel > 255 for channel in color):
            print("Each number stays between 0 and 255.")
            continue
        return color


def show(strip, color):
    strip.fill(color)
    strip.show()
    print(f"Sent rgb {color[0]} {color[1]} {color[2]} to every LED.")
    print("If the strip did not change, the data pin is not reaching the first LED.")


def main():
    args = parse_args()
    if args.color is not None and any(channel < 0 or channel > 255 for channel in args.color):
        raise SystemExit("Each --color number stays between 0 and 255.")
    strip = open_strip(args.pin, args.leds, args.brightness)
    if args.order == "rgb":
        strip.byteorder = "RGB"
    print(strip.data_note)
    try:
        if args.color is not None:
            show(strip, tuple(args.color))
            print("Holding that color. Ctrl+C turns the strip off.")
            while True:
                time.sleep(0.5)
        while True:
            color = ask_rgb()
            if color is None:
                print("Lights off.")
                break
            show(strip, color)
    except KeyboardInterrupt:
        print("\nLights off.")
    finally:
        lights_off(strip)


if __name__ == "__main__":
    main()
