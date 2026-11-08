"""Curl the string-driven finger from a number another Pi publishes on MQTT.

Same motion as finger_curl.py: 0 is open, 90 is a 90 degree pull, the pose
holds for 10 seconds, then the finger opens. Paste the topic when asked.
The other Pi publishes a plain number on that topic, for example 45.

Broker, from the Lab 6 notes: farlab.infosci.cornell.edu port 1883,
user idd, password device@theFarm. Topics on that broker start with IDD/.

  python finger_curl_mqtt.py --channel 0

The other Pi can send a curl with:

  mosquitto_pub -h farlab.infosci.cornell.edu -p 1883 -t 'IDD/yourteam/finger' -m '45' -u idd -P 'device@theFarm'
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


def ask_topic():
    while True:
        typed = input("MQTT topic (paste the channel): ").strip()
        if not typed:
            print("Paste a topic, for example IDD/yourteam/finger.")
            continue
        if not typed.startswith("IDD/"):
            print("This broker only delivers topics that start with IDD/.")
            continue
        return typed


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
        for key in ("curl", "angle", "value", "degree", "degrees"):
            if key in payload:
                try:
                    return float(payload[key])
                except (TypeError, ValueError):
                    return None
    return None


def listen(topic, curls):
    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            print(f"MQTT refused the connection (code {rc}).")
            return
        client.subscribe(topic)
        print(f"Listening on {topic}. Waiting for a number from {CURL_MIN:.0f} to {CURL_MAX:.0f}.")

    def on_message(client, userdata, msg):
        text = msg.payload.decode("utf-8", errors="replace")
        value = read_number(text)
        if value is None:
            print(f"Ignored {text.strip()!r}. Expected a number.")
            return
        if value < CURL_MIN or value > CURL_MAX:
            print(f"Ignored {value:.0f}. Curl stays between {CURL_MIN:.0f} and {CURL_MAX:.0f}.")
            return
        print(f"Heard {value:.0f} on {msg.topic}")
        curls.put(value)

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
    topic = ask_topic()
    direction = "down" if args.reverse else "up"
    print(
        f"Finger on pHAT channel {args.channel}. "
        f"0 is open at {OPEN_DEG:.0f}°. "
        f"90 curls {CURL_MAX:.0f}° {direction} the servo scale, "
        f"holds {HOLD_S:.0f}s, then opens."
    )
    print("The pHAT needs its own USB-C cable for servo power.")
    curls = queue.Queue()
    client = listen(topic, curls)
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
