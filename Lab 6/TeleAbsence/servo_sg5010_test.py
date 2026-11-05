"""Test a TowerPro SG-5010 from the keyboard. Standalone. BCM pin numbering.

This lab hub's existing servo code drives a SparkFun Servo pHAT over I2C.
It does not assign a GPIO pin to an SG-5010. Pass the signal pin yourself
with --pin. The number is BCM, the same numbering as board.D18 / GPIO18,
not the physical header pin. The script prints the physical pin beside it
so you can check the wire.

Wiring assumptions
  Servo yellow or orange (signal) -> the BCM GPIO you pass to --pin.
  Servo red (power) -> a separate regulated 5 V to 6 V supply.
    The SG-5010 is specified for about 4.8 V to 6.0 V.
    Do not power it from a Pi GPIO pin, the Pi 3.3 V pin, or the Pi 5 V rail.
  Servo brown or black (ground) -> that supply's ground, and that ground
    tied to a Pi ground pin. The signal is meaningless without a common ground.
  Nothing else in this repo claims the pin you choose. GPIO 2 and 3 are I2C
    (Qwiic and the Servo pHAT). GPIO 5, 22, 23, 24, and 25 are used by the
    Mini PiTFT in Lab 2 and Lab 6. Avoid those if that hardware is stacked.

Safety
  Take the horn and any hand or string linkage off before the first run.
  The first pulse can jump, because the script cannot know where the shaft
  was sitting while it was unpowered. Later moves step one degree at a time.
  Keep the sweep at the default 5 degrees until the horn is back on and you
  have seen which way is left.

Pulse calibration
  Defaults are a narrow window around the usual 1500 µs center, not the
  servo's full travel. A degree here is --us-per-deg microseconds (default
  10), clamped so the pulse stays inside --min-us and --max-us (default
  1100 to 1900). Five degrees is about 50 µs, a small nudge.
  If the shaft barely moves, raise --us-per-deg a little, for example 15.
  Widen --min-us / --max-us only a few tens of microseconds at a time, with
  the mechanism unloaded, and stop if the horn buzzes or stalls against a stop.
  Do not start from a 500 to 2500 µs, 0 to 180 degree assumption.

Run, from this folder, with the pin you actually wired (example only: BCM 18,
which is physical pin 12):

  python servo_sg5010_test.py --pin 18

lgpio is the PWM library. Lab 6 already lists lgpio>=0.2.2.0 for the Pi 5.
RPi.GPIO, including the copy frozen in Lab 4, does not provide this PWM on a
Pi 5. Install lgpio only if the script reports that it is missing:

  python -m pip install 'lgpio>=0.2.2.0'

What this repo does not settle
  There is no TeleAbsence hardware note, no SG-5010 wire list, and no recorded
  OS image version. The Pi model used elsewhere here is a Pi 5. Confirm the
  signal pin, that the servo supply is 5 V to 6 V, and that its ground is tied
  to Pi ground before trusting a larger sweep.
"""

import argparse
import sys
import time

# BCM number -> physical pin on the 40-pin header. Used only for the label.
BCM_TO_PHYSICAL = {
    0: 27, 1: 28, 2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21,
    10: 19, 11: 23, 12: 32, 13: 33, 14: 8, 15: 10, 16: 36, 17: 11, 18: 12,
    19: 35, 20: 38, 21: 40, 22: 15, 23: 16, 24: 18, 25: 22, 26: 37, 27: 13,
}

# Pi 5 kernels have exposed the 40-pin header as gpiochip4 and, later, gpiochip0.
GPIOCHIP_CANDIDATES = (0, 4)
PERIOD_US = 20000
PWM_HZ = 50


def parse_args():
    parser = argparse.ArgumentParser(
        description="Keyboard test for one SG-5010. --pin is a BCM number, not a physical pin.",
    )
    parser.add_argument("--pin", type=int, required=True, help="BCM GPIO for the signal wire. No default.")
    parser.add_argument("--center-deg", type=float, default=90.0, help="center angle in degrees (default 90)")
    parser.add_argument("--center-us", type=float, default=1500.0, help="pulse width at center, microseconds (default 1500)")
    parser.add_argument("--min-us", type=float, default=1100.0, help="shortest allowed pulse, microseconds (default 1100)")
    parser.add_argument("--max-us", type=float, default=1900.0, help="longest allowed pulse, microseconds (default 1900)")
    parser.add_argument("--us-per-deg", type=float, default=10.0, help="microseconds of pulse per degree (default 10)")
    parser.add_argument("--step-s", type=float, default=0.02, help="seconds between 1 degree steps (default 0.02)")
    args = parser.parse_args()
    if args.pin not in BCM_TO_PHYSICAL:
        raise SystemExit(f"BCM {args.pin} is not a 40-pin header GPIO. Pass a BCM number, for example --pin 18.")
    if not (500.0 <= args.min_us < args.center_us < args.max_us <= 2500.0):
        raise SystemExit("--min-us, --center-us, and --max-us must be in order and inside 500..2500.")
    if args.us_per_deg <= 0 or args.step_s <= 0:
        raise SystemExit("--us-per-deg and --step-s must be greater than 0.")
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
    raw = args.center_us + (angle - args.center_deg) * args.us_per_deg
    limited = min(args.max_us, max(args.min_us, raw))
    return limited, abs(limited - raw) > 0.5


class Servo:
    def __init__(self, args):
        try:
            import lgpio
        except ImportError as exc:
            raise SystemExit(
                "lgpio is not installed for this Python.\n"
                "  python -m pip install 'lgpio>=0.2.2.0'"
            ) from exc
        self.lgpio = lgpio
        self.args = args
        self.handle = None
        self.chip = None
        self.angle = None
        self._open()

    def _open(self):
        pin = self.args.pin
        errors = []
        for chip in GPIOCHIP_CANDIDATES:
            try:
                handle = self.lgpio.gpiochip_open(chip)
            except self.lgpio.error as exc:
                errors.append(f"gpiochip{chip}: {exc}")
                continue
            try:
                self.lgpio.gpio_claim_output(handle, pin, 0)
            except self.lgpio.error as exc:
                errors.append(f"gpiochip{chip} refused BCM {pin}: {exc}")
                self.lgpio.gpiochip_close(handle)
                continue
            self.handle = handle
            self.chip = chip
            return
        detail = "\n".join(errors) or "no gpiochip could be opened"
        raise SystemExit(
            "Could not claim BCM "
            f"{pin} on gpiochip 0 or 4.\n{detail}\n"
            "On a Pi 5 the 40-pin header is one of those two chips. "
            "Confirm the pin is free and that this is the Pi's own Python environment."
        )

    def set_pulse(self, pulse_us):
        duty = max(0.0, min(100.0, pulse_us / PERIOD_US * 100.0))
        self.lgpio.tx_pwm(self.handle, self.args.pin, PWM_HZ, duty)

    def _remember(self, pulse):
        self.angle = self.args.center_deg + (pulse - self.args.center_us) / self.args.us_per_deg
        return self.angle

    def move_to(self, target):
        pulse, limited = pulse_for(target, self.args)
        if self.angle is None:
            self.set_pulse(pulse)
            self._remember(pulse)
            return pulse, limited
        step = 1.0 if target > self.angle else -1.0
        angle = self.angle
        while (step > 0 and angle < target) or (step < 0 and angle > target):
            gap = abs(target - angle)
            angle = target if gap <= 1.0 else angle + step
            pulse, limited = pulse_for(angle, self.args)
            self.set_pulse(pulse)
            self._remember(pulse)
            if limited:
                break
            time.sleep(self.args.step_s)
        return pulse, limited

    def close(self):
        if self.handle is None:
            return
        try:
            self.lgpio.tx_pwm(self.handle, self.args.pin, 0, 0)
            self.lgpio.gpio_free(self.handle, self.args.pin)
        finally:
            self.lgpio.gpiochip_close(self.handle)
            self.handle = None


def pin_label(bcm):
    return f"BCM {bcm} (physical pin {BCM_TO_PHYSICAL[bcm]})"


def show(args, sweep, target, pulse, limited):
    limit = "  pulse window stopped this move" if limited else ""
    print(
        f"center {args.center_deg:g}°   sweep {sweep:g}°   "
        f"target {target:g}°   pulse {pulse:.0f} µs   {pin_label(args.pin)}{limit}"
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
    print(f"Signal numbering is BCM. You asked for {pin_label(args.pin)}.")
    print(
        f"Center {args.center_deg:g}° is {args.center_us:g} µs. "
        f"Pulses stay inside {args.min_us:g}..{args.max_us:g} µs "
        f"at {args.us_per_deg:g} µs/degree."
    )
    sweep = ask_sweep()
    servo = Servo(args)
    try:
        pulse, limited = servo.move_to(args.center_deg)
        print("At center. Keys: l left, r right, c center, + or - sweep by 1°, q quit.")
        show(args, sweep, args.center_deg, pulse, limited)
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
            pulse, limited = servo.move_to(target)
            show(args, sweep, servo.angle, pulse, limited)
    except KeyboardInterrupt:
        print("\nStopping the pulse.")
    finally:
        servo.close()


if __name__ == "__main__":
    main()
