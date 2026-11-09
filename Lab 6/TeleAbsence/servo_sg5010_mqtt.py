"""Drive a TowerPro SG-5010 from the same bend channel as finger_curl_mqtt.py.

The channel number is still the horn angle, from 0 to 180, and this Pi still
publishes IN PROGRESS or STOP on IDD/djv/text. What changes is the pulse
that moves this servo. An SG-5010 takes about 500 µs at 0° and 2500 µs at
180°. The narrower 1100 to 1900 µs window leaves most of that travel unused,
so the horn barely turns.

The pHAT's own USB-C jack powers the motor. The Pi's 5 V pin does not.
i2cdetect can show 40 while that cable is unplugged, and the servo will not
move. Stop the script if the horn buzzes against its stop.

  python servo_sg5010_mqtt.py --channel 0
"""

import sys
import time

from finger_curl import Servo, parse_args
from finger_curl_mqtt import (
    LISTEN_S,
    MQTT_TOPIC,
    ROTATION_MAX,
    STOP,
    TEXT_TOPIC,
    Latest,
    horn_angle,
    listen,
    publish_status,
    status_for,
)

# SG-5010 specified travel. Override with --min-us / --max-us if it stalls.
SG5010_MIN_US = 500
SG5010_MAX_US = 2500


def sg5010_args():
    args = parse_args()
    if "--min-us" not in sys.argv:
        args.min_us = SG5010_MIN_US
    if "--max-us" not in sys.argv:
        args.max_us = SG5010_MAX_US
    args.step_s = min(args.step_s, LISTEN_S / ROTATION_MAX)
    return args


def main():
    args = sg5010_args()
    print(
        f"SG-5010 on pHAT channel {args.channel}. "
        f"Pulse {args.min_us} µs at 0° and {args.max_us} µs at {ROTATION_MAX:.0f}°. "
        f"Bend topic {MQTT_TOPIC}. Status topic {TEXT_TOPIC}."
    )
    print("Plug USB-C into the Servo pHAT. That jack powers the SG-5010.")
    latest = Latest()
    client = listen(latest)
    servo = Servo(args)
    shown = None
    sent = None
    try:
        servo.move_to(horn_angle(0.0, args.reverse))
        print(f"Horn at {servo.angle:.0f}°.")
        next_tick = time.monotonic()
        while True:
            now = time.monotonic()
            if now < next_tick:
                time.sleep(next_tick - now)
            next_tick = time.monotonic() + LISTEN_S
            degrees = latest.get()
            if degrees is None:
                continue
            if (
                shown is not None
                and abs(degrees - shown) < 1.0
                and status_for(degrees) == status_for(shown)
            ):
                continue
            servo.move_to(horn_angle(degrees, args.reverse))
            shown = degrees
            print(f"Channel {degrees:.0f}°. Horn at {servo.angle:.0f}°.")
            status = status_for(degrees)
            if status != sent:
                publish_status(client, status)
                sent = status
    except KeyboardInterrupt:
        print("\nOpening, then stopping the pulse.")
        servo.move_to(horn_angle(0.0, args.reverse))
        if sent != STOP:
            publish_status(client, STOP)
    finally:
        client.loop_stop()
        client.disconnect()
        servo.close()


if __name__ == "__main__":
    main()
