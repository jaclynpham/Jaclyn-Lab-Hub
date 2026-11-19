"""Paint the whole WS2812B strip one color that you type.

No distance sensor. Every LED gets the same red, green, and blue numbers,
from 0 to 255. A working strip looks like one flat color, not a rainbow.

  python led_test.py
  python led_test.py --leds 60 --pin 18

Try 255 0 0 for red, 0 255 0 for green, and 0 0 255 for blue.
If those three come out swapped, run again with --order rgb.
q turns the strip off.
"""

import argparse

from hug import lights_off, open_strip


def parse_args():
    parser = argparse.ArgumentParser(description="Set every LED to one typed RGB color.")
    parser.add_argument("--pin", type=int, default=18, help="GPIO for the strip data wire (default 18)")
    parser.add_argument("--leds", type=int, default=30, help="number of LEDs on the strip (default 30)")
    parser.add_argument("--brightness", type=float, default=1.0, help="strip brightness, 0 to 1 (default 1)")
    parser.add_argument("--order", choices=("grb", "rgb"), default="grb", help="WS2812B color order (default grb)")
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


def main():
    args = parse_args()
    strip = open_strip(args.pin, args.leds, args.brightness)
    if args.order == "rgb":
        strip.byteorder = "RGB"
    print(f"{args.leds} LEDs on GPIO {args.pin}. The whole strip uses the color you type.")
    try:
        while True:
            color = ask_rgb()
            if color is None:
                print("Lights off.")
                break
            strip.fill(color)
            strip.show()
            print(f"Set every LED to rgb {color[0]} {color[1]} {color[2]}.")
    except KeyboardInterrupt:
        print("\nLights off.")
    finally:
        lights_off(strip)


if __name__ == "__main__":
    main()
