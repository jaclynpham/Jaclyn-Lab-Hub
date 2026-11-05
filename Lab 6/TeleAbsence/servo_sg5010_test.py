"""Test a TowerPro SG-5010 plugged into the SparkFun Servo pHAT.

The pHAT makes the servo pulses. A BCM pin such as GPIO 18 does not reach a
servo screwed into the pHAT. i2cdetect showing 40 and 70 is this board: 0x40
is the PCA9685, and 0x70 is that chip's all-call address, not a second device.

Wiring
  Servo plugged into one numbered header on the pHAT. That number is --channel
  (0, 1, 2, ...). This script does not guess it.
  Pi powered by its own USB-C supply.
  A second USB-C cable plugged into the Servo pHAT itself. That jack powers
  the servo. The PCA9685 still answers on I2C when this cable is missing, so
  i2cdetect can look fine while the servo has no power and does not move.
  Do not feed the servo from a Pi GPIO pin, the Pi 3.3 V pin, or the Pi 5 V rail.

Safety
  Horn and any hand or string linkage off for the first run.
  The first pulse can jump. Later l / r / c moves step one degree at a time.
  Leave the sweep at 5 degrees until you have seen which way is left.

Pulse calibration
  Angle 0 maps to --min-us and angle 180 maps to --max-us. Defaults are
  1100 µs and 1900 µs, so center (90°) is 1500 µs. That is inside the usual
  SG-5010 travel, not a 500 to 2500 µs full sweep. Widen the two limits a few
  tens of microseconds at a time, unloaded, and stop if the servo buzzes or
  stalls against its stop.

Run from this folder. Channel 0 is only an example; use the number printed
next to the header you used:

  python servo_sg5010_test.py --channel 0

If the import fails:

  python -m pip install adafruit-circuitpython-servokit
"""

import argparse
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(
        description="Keyboard test for one SG-5010 on the Servo pHAT. --channel is the header number, not a GPIO pin.",
    )
    parser.add_argument("--channel", type=int, required=True, help="pHAT servo header, usually 0 through 15")
    parser.add_argument("--address", type=lambda text: int(text, 0), default=0x40, help="PCA9685 I2C address (default 0x40)")
    parser.add_argument("--center-deg", type=float, default=90.0, help="center angle in degrees (default 90)")
    parser.add_argument("--min-us", type=int, default=1100, help="pulse at 0 degrees, microseconds (default 1100)")
    parser.add_argument("--max-us", type=int, default=1900, help="pulse at 180 degrees, microseconds (default 1900)")
    parser.add_argument("--step-s", type=float, default=0.02, help="seconds between 1 degree steps (default 0.02)")
    args = parser.parse_args()
    if not 0 <= args.channel <= 15:
        raise SystemExit("--channel must be 0 through 15.")
    if not (500 <= args.min_us < args.max_us <= 2500):
        raise SystemExit("--min-us and --max-us must be in order and inside 500..2500.")
    if not 0.0 <= args.center_deg <= 180.0 or args.step_s <= 0:
        raise SystemExit("--center-deg must be 0..180 and --step-s must be greater than 0.")
    return args


def ask_sweep():
    while True:
        typed = input("Sweep amount in degrees [5]: ").strip()
        if typed == "":
            return 5.0
        try:
            sweep = float(typed)
        except ValueError:
            print("Enter a number of degrees, or press Enter for 5.")
            continue
        if sweep <= 0:
            print("Sweep has to be greater than 0.")
            continue
        return sweep


def pulse_for(angle, args):
    span = args.max_us - args.min_us
    return args.min_us + (angle / 180.0) * span


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
            return pulse_for(target, self.args)
        step = 1.0 if target > self.angle else -1.0
        angle = self.angle
        while (step > 0 and angle < target) or (step < 0 and angle > target):
            gap = abs(target - angle)
            angle = target if gap <= 1.0 else angle + step
            self.output.angle = angle
            self.angle = angle
            time.sleep(self.args.step_s)
        return pulse_for(self.angle, self.args)

    def close(self):
        if self.angle is None:
            return
        self.output.angle = None
        self.angle = None


def show(args, sweep, target, pulse):
    print(
        f"center {args.center_deg:g}°   sweep {sweep:g}°   "
        f"target {target:g}°   pulse {pulse:.0f} µs   "
        f"pHAT channel {args.channel} at I2C {args.address:#x}"
    )


def read_key():
    if not sys.stdin.isatty():
        line = input("l, r, c, +, -, q: ").strip()
        return line[:1] if line else ""
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        char = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    if char == "\x03":
        raise KeyboardInterrupt
    return char


def main():
    args = parse_args()
    print(
        f"Servo pHAT channel {args.channel}, I2C {args.address:#x}. "
        "This is not a GPIO pin."
    )
    print(
        "The pHAT needs its own USB-C cable for servo power. "
        "The Pi's USB-C cable does not power the servo."
    )
    print(
        f"Center {args.center_deg:g}° is {pulse_for(args.center_deg, args):.0f} µs. "
        f"0° is {args.min_us} µs and 180° is {args.max_us} µs."
    )
    sweep = ask_sweep()
    servo = Servo(args)
    try:
        pulse = servo.move_to(args.center_deg)
        print("At center. Keys: l left, r right, c center, + or - sweep by 1°, q quit.")
        show(args, sweep, servo.angle, pulse)
        while True:
            key = read_key()
            if key in ("q", "Q"):
                servo.move_to(args.center_deg)
                print("Back at center. Stopping the pulse.")
                break
            if key == "l":
                target = args.center_deg - sweep
            elif key == "r":
                target = args.center_deg + sweep
            elif key == "c":
                target = args.center_deg
            elif key == "+":
                sweep += 1.0
                target = servo.angle if servo.angle is not None else args.center_deg
            elif key == "-":
                sweep = max(1.0, sweep - 1.0)
                target = servo.angle if servo.angle is not None else args.center_deg
            else:
                continue
            pulse = servo.move_to(target)
            show(args, sweep, servo.angle, pulse)
    except KeyboardInterrupt:
        print("\nStopping the pulse.")
    finally:
        servo.close()


if __name__ == "__main__":
    main()
