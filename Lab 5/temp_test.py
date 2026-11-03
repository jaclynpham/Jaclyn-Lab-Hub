import time


def create_sensor():
    """Create the DHT11 used by the temperature-enabled night watch."""
    try:
        import board
        import adafruit_dht
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "DHT11 support is missing from this Python environment. "
            "Run: .venv/bin/pip install -r requirements.txt"
        ) from exc

    return adafruit_dht.DHT11(board.D4, use_pulseio=False)


def read_sensor(sensor, attempts=3, retry_delay=1.1):
    """Return one reading, retrying transient DHT11 checksum/read failures."""
    for attempt in range(attempts):
        try:
            temperature = sensor.temperature
            humidity = sensor.humidity
            if temperature is None or humidity is None:
                raise RuntimeError("incomplete reading")
            return float(temperature), float(humidity)
        except RuntimeError as exc:
            if attempt == attempts - 1:
                print("Sensor read error:", exc, flush=True)
                return None
            print(
                f"Sensor read error: {exc}; retrying ({attempt + 1}/{attempts - 1})",
                flush=True,
            )
            time.sleep(retry_delay)


def run_sensor_test():
    sensor = create_sensor()
    try:
        while True:
            reading = read_sensor(sensor)
            if reading is not None:
                temperature, humidity = reading
                print(f"Temperature: {temperature:g}°C")
                print(f"Humidity: {humidity:g}%")
            time.sleep(2)
    except KeyboardInterrupt:
        print("Stopping")
    finally:
        sensor.exit()


if __name__ == "__main__":
    run_sensor_test()
