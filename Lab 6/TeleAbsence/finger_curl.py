"""Curl one string-driven finger with a number from 0 to 90.

0 leaves the finger open. 90 is a 90 degree pull on the string, the full
curl this script will command. It holds that curl for 10 seconds, then
returns to open. The SG-5010 cannot turn farther than that without hitting
its stop. The open position sits at 45 degrees on the servo and a full curl
sits at 135, so the 90 degree travel stays off both ends.
If the finger straightens when you ask it to curl, pass --reverse.

Same Servo pHAT as servo_sg5010_test.py. Channel is the header number, not
a GPIO pin. The pHAT needs its own USB-C cable for servo power.

  python finger_curl.py --channel 0
"""

import argparse
import time

CURL_MIN = 0.0
CURL_MAX = 90.0
OPEN_DEG = 45.0
HOLD_S = 10.0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Set a robotic finger curl from 0 (open) to 90 (fully curled).",
    )
    parser.add_argument("--channel", type=int, required=True, help="pHAT servo header, usually 0 through 15")
    parser.add_argument("--address", type=lambda text: int(text, 0), default=0x40, help="PCA9685 I2C address (default 0x40)")
    parser.add_argument("--reverse", action="store_true", help="curl toward a smaller servo angle")
    parser.add_argument("--min-us", type=int, default=1100, help="pulse at servo 0 degrees (default 1100)")
    parser.add_argument("--max-us", type=int, default=1900, help="pulse at servo 180 degrees (default 1900)")
    parser.add_argument("--step-s", type=float, default=0.02, help="seconds between 1 degree steps (default 0.02)")
    args = parser.parse_args()
    if not 0 <= args.channel <= 15:
        raise SystemExit("--channel must be 0 through 15.")
    if not (500 <= args.min_us < args.max_us <= 2500):
        raise SystemExit("--min-us and --max-us must be in order and inside 500..2500.")
    if args.step_s <= 0:
        raise SystemExit("--step-s must be greater than 0.")
    return args


def servo_angle(curl, reverse):
    if reverse:
        return OPEN_DEG + CURL_MAX - curl
    return OPEN_DEG + curl


def pulse_for(angle, args):
    span = args.max_us - args.min_us
    return args.min_us + (angle / 180.0) * span


def ask_curl():
    while True:
        typed = input(f"Curl {CURL_MIN:.0f}-{CURL_MAX:.0f} (q to quit): ").strip()
        if typed.lower() in ("q", "quit"):
            return None
        try:
            curl = float(typed)
        except ValueError:
            print(f"Enter a number from {CURL_MIN:.0f} to {CURL_MAX:.0f}.")
            continue
        if curl < CURL_MIN or curl > CURL_MAX:
            print(f"Curl stays between {CURL_MIN:.0f} and {CURL_MAX:.0f}.")
            continue
        return curl


class Servo:
    def __init__(self, args):
        try:
            from adafruit_servokit import ServoKit
        except ImportError as exc:
            raise SystemExit(
                "adafruit-circuitpython-servokit is not installed for this Python.\n"
                "  python -m pip install adafruit-circuitpython-servokit"
            ) from exc
        self.args = args
        self.angle = None
        try:
            kit = ServoKit(channels=16, address=args.address)
        except Exception as exc:
            raise SystemExit(
                f"Could not open the Servo pHAT at I2C address {args.address:#x}.\n"
                "i2cdetect should show 40. Check that the pHAT is seated on the Pi header.\n"
                f"({exc})"
            ) from exc
        self.output = kit.servo[args.channel]
        self.output.set_pulse_width_range(args.min_us, args.max_us)
        self.output.angle = None

    def move_to(self, target):
        target = min(180.0, max(0.0, target))
        if self.angle is None:
            self.output.angle = target
            self.angle = target
            return
        step = 1.0 if target > self.angle else -1.0
        angle = self.angle
        while (step > 0 and angle < target) or (step < 0 and angle > target):
            gap = abs(target - angle)
            angle = target if gap <= 1.0 else angle + step
            self.output.angle = angle
            self.angle = angle
            time.sleep(self.args.step_s)

    def close(self):
        if self.angle is None:
            return
        self.output.angle = None
        self.angle = None


def main():
    args = parse_args()
    direction = "down" if args.reverse else "up"
    print(
        f"Finger on pHAT channel {args.channel}. "
        f"0 is open at {OPEN_DEG:.0f}°. "
        f"90 curls {CURL_MAX:.0f}° {direction} the servo scale, "
        f"holds {HOLD_S:.0f}s, then opens."
    )
    print("The pHAT needs its own USB-C cable for servo power.")
    servo = Servo(args)
    try:
        servo.move_to(servo_angle(0.0, args.reverse))
        print(f"Open. Servo {servo.angle:.0f}°.")
        while True:
            curl = ask_curl()
            if curl is None:
                servo.move_to(servo_angle(0.0, args.reverse))
                print("Open. Stopping the pulse.")
                break
            servo.move_to(servo_angle(curl, args.reverse))
            print(
                f"Curl {curl:.0f}°   servo {servo.angle:.0f}°   "
                f"pulse {pulse_for(servo.angle, args):.0f} µs   "
                f"holding {HOLD_S:.0f}s"
            )
            time.sleep(HOLD_S)
            servo.move_to(servo_angle(0.0, args.reverse))
            print(f"Open. Servo {servo.angle:.0f}°.")
    except KeyboardInterrupt:
        print("\nOpening, then stopping the pulse.")
        servo.move_to(servo_angle(0.0, args.reverse))
    finally:
        servo.close()


if __name__ == "__main__":
    main()
