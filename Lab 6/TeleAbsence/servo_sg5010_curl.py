"""Type a degree and turn a TowerPro SG-5010, the same way as finger_curl.py.

Enter a number from 0 to 180. The horn goes to that angle, holds for 10
seconds, then returns to 0. q quits. Pulse is the SG-5010's full travel:
500 µs at 0° and 2500 µs at 180°.

The Servo pHAT needs its own USB-C cable. That jack powers the motor.
Stop if the horn buzzes against its stop.

  python servo_sg5010_curl.py --channel 0
"""

import argparse
import time

from finger_curl import Servo, pulse_for

ROTATION_MIN = 0.0
ROTATION_MAX = 180.0
HOLD_S = 10.0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Turn an SG-5010 to a typed angle from 0 to 180, hold 10 seconds, then return to 0.",
    )
    parser.add_argument("--channel", type=int, required=True, help="pHAT servo header, usually 0 through 15")
    parser.add_argument("--address", type=lambda text: int(text, 0), default=0x40, help="PCA9685 I2C address (default 0x40)")
    parser.add_argument("--reverse", action="store_true", help="turn toward the other end of the travel")
    parser.add_argument("--min-us", type=int, default=500, help="pulse at 0 degrees, microseconds (default 500)")
    parser.add_argument("--max-us", type=int, default=2500, help="pulse at 180 degrees, microseconds (default 2500)")
    parser.add_argument("--step-s", type=float, default=0.02, help="seconds between 1 degree steps (default 0.02)")
    args = parser.parse_args()
    if not 0 <= args.channel <= 15:
        raise SystemExit("--channel must be 0 through 15.")
    if not (500 <= args.min_us < args.max_us <= 2500):
        raise SystemExit("--min-us and --max-us must be in order and inside 500..2500.")
    if args.step_s <= 0:
        raise SystemExit("--step-s must be greater than 0.")
    return args


def horn_angle(degrees, reverse):
    if reverse:
        return ROTATION_MAX - degrees
    return degrees


def ask_degrees():
    while True:
        typed = input(f"Degrees {ROTATION_MIN:.0f}-{ROTATION_MAX:.0f} (q to quit): ").strip()
        if typed.lower() in ("q", "quit"):
            return None
        try:
            degrees = float(typed)
        except ValueError:
            print(f"Enter a number from {ROTATION_MIN:.0f} to {ROTATION_MAX:.0f}.")
            continue
        if degrees < ROTATION_MIN or degrees > ROTATION_MAX:
            print(f"Degrees stay between {ROTATION_MIN:.0f} and {ROTATION_MAX:.0f}.")
            continue
        return degrees


def main():
    args = parse_args()
    print(
        f"SG-5010 on pHAT channel {args.channel}. "
        f"Type {ROTATION_MIN:.0f} to {ROTATION_MAX:.0f}. "
        f"The horn holds {HOLD_S:.0f}s, then returns to 0. "
        f"Pulse {args.min_us} µs at 0° and {args.max_us} µs at {ROTATION_MAX:.0f}°."
    )
    print("Plug USB-C into the Servo pHAT. That jack powers the SG-5010.")
    servo = Servo(args)
    try:
        servo.move_to(horn_angle(0.0, args.reverse))
        print(f"Horn at {servo.angle:.0f}°.")
        while True:
            degrees = ask_degrees()
            if degrees is None:
                servo.move_to(horn_angle(0.0, args.reverse))
                print("Horn at 0°. Stopping the pulse.")
                break
            servo.move_to(horn_angle(degrees, args.reverse))
            print(
                f"Channel {degrees:.0f}°. Horn at {servo.angle:.0f}°. "
                f"Pulse {pulse_for(servo.angle, args):.0f} µs. Holding {HOLD_S:.0f}s."
            )
            time.sleep(HOLD_S)
            servo.move_to(horn_angle(0.0, args.reverse))
            print(f"Horn at {servo.angle:.0f}°.")
    except KeyboardInterrupt:
        print("\nReturning to 0, then stopping the pulse.")
        servo.move_to(horn_angle(0.0, args.reverse))
    finally:
        servo.close()


if __name__ == "__main__":
    main()
