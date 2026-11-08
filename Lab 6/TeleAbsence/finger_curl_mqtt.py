"""Curl the string-driven finger from the live bend on IDD/djv/bend.

Another Pi publishes a plain angle, several times a second, from 0 at rest
up through the bend. This script waits out one bend, then curls to the
deepest angle in it, holds for 10 seconds, and opens. A resting stream of
0.0 does not move the servo. Angles above 90 are treated as a full curl.

Broker, from the Lab 6 notes: farlab.infosci.cornell.edu port 1883,
user idd, password device@theFarm.

  python finger_curl_mqtt.py --channel 0
"""

import json
import queue
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
    HOLD_S,
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

# Below this, the finger on the other Pi counts as open.
REST_DEG = 5.0
# A bend that stays inside this band for STABLE_S is the pose to copy,
# even if they never let the finger open again.
STABLE_BAND = 2.0
STABLE_S = 1.0


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


class BendWatch:
    """Turn the live stream into one curl command per bend."""

    def __init__(self, curls):
        self.curls = curls
        self.peak = 0.0
        self.holding = False
        self.anchor = None
        self.anchor_at = None

    def sample(self, value):
        value = min(CURL_MAX, max(CURL_MIN, value))
        if value <= REST_DEG:
            if self.peak > REST_DEG and not self.holding:
                self._commit(self.peak)
            elif self.holding:
                self.holding = False
            self.peak = 0.0
            self.anchor = None
            return
        if self.holding:
            return
        if self.peak <= REST_DEG:
            print(f"Bend started at {value:.0f}°.")
        self.peak = max(self.peak, value)
        now = time.monotonic()
        if self.anchor is None or abs(value - self.anchor) > STABLE_BAND:
            self.anchor = value
            self.anchor_at = now
            return
        if now - self.anchor_at >= STABLE_S:
            self._commit(self.peak)

    def _commit(self, curl):
        print(f"Bend settled at {curl:.0f}°.")
        self.curls.put(curl)
        self.holding = True
        self.peak = 0.0
        self.anchor = None


def listen(curls):
    watch = BendWatch(curls)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            print(f"MQTT refused the connection (code {rc}).")
            return
        client.subscribe(MQTT_TOPIC)
        print(f"Listening on {MQTT_TOPIC}.")

    def on_message(client, userdata, msg):
        text = msg.payload.decode("utf-8", errors="replace")
        value = read_number(text)
        if value is None:
            print(f"Ignored {text.strip()!r}. Expected a number.")
            return
        watch.sample(value)

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
    direction = "down" if args.reverse else "up"
    print(
        f"Finger on pHAT channel {args.channel}, topic {MQTT_TOPIC}. "
        f"0 is open at {OPEN_DEG:.0f}°. "
        f"90 curls {CURL_MAX:.0f}° {direction} the servo scale, "
        f"holds {HOLD_S:.0f}s, then opens."
    )
    print("The pHAT needs its own USB-C cable for servo power.")
    curls = queue.Queue()
    client = listen(curls)
    servo = Servo(args)
    try:
        servo.move_to(servo_angle(0.0, args.reverse))
        print(f"Open. Servo {servo.angle:.0f}°.")
        while True:
            curl = curls.get()
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
        client.loop_stop()
        client.disconnect()
        servo.close()


if __name__ == "__main__":
    main()
