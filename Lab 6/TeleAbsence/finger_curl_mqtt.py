"""Follow the live bend on IDD/djv/bend, once a second.

The number on that channel is the horn angle, from 0 to 180. This script
keeps the newest number and moves the servo there once a second. 0 is the
start of the travel and 180 is a full turn.

Each time that number is not 0, it publishes IN PROGRESS on IDD/djv/text.
When the number is 0, it publishes STOP. The other Pi only receives those
messages.

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

from finger_curl import Servo, parse_args

MQTT_BROKER = "farlab.infosci.cornell.edu"
MQTT_PORT = 1883
MQTT_USERNAME = "idd"
MQTT_PASSWORD = "device@theFarm"
MQTT_TOPIC = "IDD/djv/bend"
TEXT_TOPIC = "IDD/djv/text"
LISTEN_S = 1.0
ROTATION_MAX = 180.0
IN_PROGRESS = "IN PROGRESS"
STOP = "STOP"


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
        latest.set(min(ROTATION_MAX, max(0.0, value)))

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


def horn_angle(degrees, reverse):
    if reverse:
        return ROTATION_MAX - degrees
    return degrees


def status_for(degrees):
    if degrees == 0:
        return STOP
    return IN_PROGRESS


def publish_status(client, status):
    client.publish(TEXT_TOPIC, status, retain=True)
    print(f"Sent {status} on {TEXT_TOPIC}.")


def main():
    args = parse_args()
    # A full 180° turn has to finish inside one listen interval.
    args.step_s = min(args.step_s, LISTEN_S / ROTATION_MAX)
    print(
        f"Finger on pHAT channel {args.channel}, topic {MQTT_TOPIC}. "
        f"The channel number is the horn angle, from 0 to {ROTATION_MAX:.0f}. "
        f"Status goes to {TEXT_TOPIC}."
    )
    print("The pHAT needs its own USB-C cable for servo power.")
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
