"""Follow the live bend on IDD/djv/bend, once a second.

The other Pi publishes a plain angle. This script keeps the newest number
and, once a second, moves the finger to it. The finger stays there until
the next update. When the channel sends 0, the finger opens. That is the
reset: there is no extra timer, because a 10 second hold would skip the
updates that arrive while it waited.

Broker, from the Lab 6 notes: farlab.infosci.cornell.edu port 1883,
user idd, password device@theFarm.

  python finger_curl_mqtt.py --channel 0
"""

import json
import threading
import time
import uuid

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:
    raise SystemExit(
        "paho-mqtt is not installed for this Python.\n"
        "  python -m pip install 'paho-mqtt<2.0'"
    ) from exc

from finger_curl import (
    CURL_MAX,
    CURL_MIN,
    OPEN_DEG,
    Servo,
    parse_args,
    pulse_for,
    servo_angle,
)

MQTT_BROKER = "farlab.infosci.cornell.edu"
MQTT_PORT = 1883
MQTT_USERNAME = "idd"
MQTT_PASSWORD = "device@theFarm"
MQTT_TOPIC = "IDD/djv/bend"
LISTEN_S = 1.0


def read_number(text):
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        return float(payload)
    if isinstance(payload, dict):
        for key in ("curl", "angle", "value", "degree", "degrees", "bend"):
            if key in payload:
                try:
                    return float(payload[key])
                except (TypeError, ValueError):
                    return None
    return None


class Latest:
    def __init__(self):
        self._lock = threading.Lock()
        self.value = None

    def set(self, value):
        with self._lock:
            self.value = value

    def get(self):
        with self._lock:
            return self.value


def listen(latest):
    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            print(f"MQTT refused the connection (code {rc}).")
            return
        client.subscribe(MQTT_TOPIC)
        print(f"Listening on {MQTT_TOPIC}, updating every {LISTEN_S:.0f}s.")

    def on_message(client, userdata, msg):
        text = msg.payload.decode("utf-8", errors="replace")
        value = read_number(text)
        if value is None:
            print(f"Ignored {text.strip()!r}. Expected a number.")
            return
        latest.set(min(CURL_MAX, max(CURL_MIN, value)))

    client = mqtt.Client(str(uuid.uuid1()))
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as exc:
        raise SystemExit(
            f"Could not reach the MQTT broker at {MQTT_BROKER}:{MQTT_PORT}.\n"
            "The Pi needs a network connection.\n"
            f"({exc})"
        ) from exc
    client.loop_start()
    return client


def main():
    args = parse_args()
    # A full curl has to finish inside one listen interval.
    args.step_s = min(args.step_s, LISTEN_S / CURL_MAX)
    direction = "down" if args.reverse else "up"
    print(
        f"Finger on pHAT channel {args.channel}, topic {MQTT_TOPIC}. "
        f"0 is open at {OPEN_DEG:.0f}°. "
        f"90 curls {CURL_MAX:.0f}° {direction} the servo scale. "
        f"The finger matches the channel once a second and opens when it sends 0."
    )
    print("The pHAT needs its own USB-C cable for servo power.")
    latest = Latest()
    client = listen(latest)
    servo = Servo(args)
    shown = None
    try:
        servo.move_to(servo_angle(0.0, args.reverse))
        print(f"Open. Servo {servo.angle:.0f}°.")
        next_tick = time.monotonic()
        while True:
            now = time.monotonic()
            if now < next_tick:
                time.sleep(next_tick - now)
            next_tick = time.monotonic() + LISTEN_S
            curl = latest.get()
            if curl is None or (shown is not None and abs(curl - shown) < 1.0):
                continue
            servo.move_to(servo_angle(curl, args.reverse))
            shown = curl
            if curl < 1.0:
                print(f"Channel {curl:.0f}°. Open, horn at {servo.angle:.0f}°.")
            else:
                print(
                    f"Channel {curl:.0f}°. Rotating {curl:.0f}° from open, "
                    f"horn at {servo.angle:.0f}°."
                )
    except KeyboardInterrupt:
        print("\nOpening, then stopping the pulse.")
        servo.move_to(servo_angle(0.0, args.reverse))
    finally:
        client.loop_stop()
        client.disconnect()
        servo.close()


if __name__ == "__main__":
    main()
