"""Ode to Joy, conducted by hand with the APDS-9960.

Same orchestra as twizzler_orchestra.py. Viola is playing when the
script starts. Each swipe changes the arrangement by one instrument:

  left to right    add the next section
  right to left   remove the section added most recently

Add order: viola, oboe, timpani, cello, flute, horn, violin.
The count stops at viola on the way down, and at the full orchestra
on the way up.

Closer to the sensor is louder. Farther away is quieter. The reading
is the sensor's own 0–255 proximity count, not a distance in
centimeters. Watch the "prox" lines and edit PROX_FAR and PROX_NEAR
to match your hand.

The sensor reports a finished swipe (left, right, up, or down). It
does not report a continuous left/right position.

Gesture and proximity share one sensor state machine. Gesture mode
starts when proximity reaches the library's entry threshold of 5, and
the chip stays there until the hand leaves. Until then, apds.proximity
is not a fresh sample, and apds.gesture() blocks while it empties the
gesture buffer. A hand held still and close can pause the prox line.
Volume follows the latest sample the main loop did get. The audio
callback only smooths that level. It never reads the sensor.
"""

import time
import board
import numpy as np
import sounddevice as sd
from adafruit_apds9960.apds9960 import APDS9960

SAMPLE_RATE = 44100
BPM = 100
# 100 BPM keeps an eighth note an integer number of samples.
EIGHTH = SAMPLE_RATE * 30 // BPM
PHRASE_EIGHTHS = 64  # 8 bars of 4/4
PHRASE = EIGHTH * PHRASE_EIGHTHS
RELEASE = int(0.03 * SAMPLE_RATE)

# Proximity counts from apds.proximity. Higher means more reflected IR,
# which usually means the hand is closer. These are not centimeters.
# Run proximity_test.py, note the number with your hand away and the
# number with your hand where you want full volume, then put those
# numbers here. With gesture enabled, a close hand can stall this
# reading; see the note at the top of the file.
PROX_FAR = 8
PROX_NEAR = 80
VOLUME_MIN = 0.22
VOLUME_MAX = 1.0
# Seconds to glide from quiet to loud, so a new reading does not click.
VOLUME_RAMP_S = 0.20
# One swipe should change the arrangement once, even if the sensor
# reports that swipe again while the hand is still leaving.
GESTURE_COOLDOWN_S = 0.40

# Same codes gesture_test.py prints.
GESTURE_LEFT = 0x03
GESTURE_RIGHT = 0x04

C2, G2 = 65.41, 98.00
C3, G3, B3 = 130.81, 196.00, 246.94
C4, D4, E4, F4, G4, A4 = 261.63, 293.66, 329.63, 349.23, 392.00, 440.00

# Synthesis order. The score arrays below stay in this order.
PARTS = ("violin", "viola", "cello", "flute", "horn", "timpani", "oboe")
# Swipe order. Index 0 is the section that is always on.
ORDER = ("viola", "oboe", "timpani", "cello", "flute", "horn", "violin")
PART_INDEX = {name: i for i, name in enumerate(PARTS)}


def _score(*notes: tuple[float, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Expand (frequency, eighths) into parallel freq, age, and duration arrays."""
    freq = np.zeros(PHRASE_EIGHTHS, dtype=np.float64)
    age = np.zeros(PHRASE_EIGHTHS, dtype=np.int32)
    dur = np.zeros(PHRASE_EIGHTHS, dtype=np.int32)
    i = 0
    for f, n in notes:
        if n < 1 or i + n > PHRASE_EIGHTHS:
            raise ValueError(f"score ran long at eighth {i}")
        freq[i : i + n] = f
        dur[i : i + n] = n
        age[i : i + n] = np.arange(n)
        i += n
    if i != PHRASE_EIGHTHS:
        raise ValueError(f"score is {i} eighths, need {PHRASE_EIGHTHS}")
    return freq, age, dur


# First phrase of Ode to Joy, in eighth notes. 0 is a rest.
VIOLIN_F, VIOLIN_AGE, VIOLIN_DUR = _score(
    (E4, 2), (E4, 2), (F4, 2), (G4, 2),
    (G4, 2), (F4, 2), (E4, 2), (D4, 2),
    (C4, 2), (C4, 2), (D4, 2), (E4, 2),
    (E4, 3), (D4, 1), (D4, 2), (0.0, 2),
    (E4, 2), (E4, 2), (F4, 2), (G4, 2),
    (G4, 2), (F4, 2), (E4, 2), (D4, 2),
    (C4, 2), (C4, 2), (D4, 2), (E4, 2),
    (D4, 3), (C4, 1), (C4, 2), (0.0, 2),
)
VIOLA_F, VIOLA_AGE, VIOLA_DUR = _score(
    (C4, 4), (D4, 2), (E4, 2),
    (E4, 2), (D4, 2), (B3, 2), (B3, 2),
    (E4, 4), (B3, 2), (C4, 2),
    (B3, 6), (0.0, 2),
    (C4, 4), (D4, 2), (E4, 2),
    (E4, 2), (D4, 2), (B3, 2), (B3, 2),
    (E4, 4), (B3, 2), (C4, 2),
    (B3, 3), (E4, 5),
)
CELLO_F, CELLO_AGE, CELLO_DUR = _score(
    (C3, 8),
    (C3, 4), (G2, 4),
    (C3, 8),
    (G2, 6), (0.0, 2),
    (C3, 8),
    (C3, 4), (G2, 4),
    (C3, 8),
    (G2, 3), (C3, 5),
)
# Flute doubles the violins an octave higher.
FLUTE_F = np.where(VIOLIN_F > 0.0, VIOLIN_F * 2.0, 0.0)
FLUTE_AGE, FLUTE_DUR = VIOLIN_AGE, VIOLIN_DUR
# Horns double the cellos an octave up, in long tones.
HORN_F, HORN_AGE, HORN_DUR = _score(
    (C4, 8),
    (C4, 4), (G3, 4),
    (C4, 8),
    (G3, 6), (0.0, 2),
    (C4, 8),
    (C4, 4), (G3, 4),
    (C4, 8),
    (G3, 3), (C4, 5),
)
TIMPANI_F, TIMPANI_AGE, TIMPANI_DUR = _score(
    (C2, 4), (C2, 4),
    (C2, 4), (G2, 4),
    (C2, 4), (C2, 4),
    (G2, 8),
    (C2, 4), (C2, 4),
    (C2, 4), (G2, 4),
    (C2, 4), (C2, 4),
    (G2, 3), (C2, 5),
)
OBOE_F, OBOE_AGE, OBOE_DUR = _score(
    (G4, 4), (A4, 2), (G4, 2),
    (E4, 4), (D4, 2), (B3, 2),
    (G4, 4), (F4, 2), (E4, 2),
    (G4, 6), (0.0, 2),
    (G4, 4), (A4, 2), (G4, 2),
    (E4, 4), (D4, 2), (B3, 2),
    (G4, 4), (F4, 2), (E4, 2),
    (D4, 3), (G4, 5),
)


def _tone(w: np.ndarray, amps: tuple[float, ...]) -> np.ndarray:
    weights = np.asarray(amps, dtype=np.float64)
    weights /= weights.sum()
    k = np.arange(1, weights.size + 1)
    return np.sin(np.asarray(w)[:, None] * k) @ weights


def _shaped(t: np.ndarray, remain: np.ndarray, attack: float, decay: float) -> np.ndarray:
    env = (1.0 - np.exp(-t * attack)) * np.exp(-t * decay)
    return env * np.clip(remain / RELEASE, 0.0, 1.0)


def _violin(t, f, remain, noise):
    vib = 0.75 * np.sin(2 * np.pi * 5.6 * t)
    w = 2 * np.pi * f * t + vib
    env = _shaped(t, remain, attack=24.0, decay=0.7) * (f > 0.0)
    bow = noise * np.exp(-t * 45.0) * 0.18
    return env * (_tone(w, (1.0, 0.55, 0.32, 0.16, 0.08)) + bow)


def _viola(t, f, remain, _noise):
    vib = 0.55 * np.sin(2 * np.pi * 4.8 * t)
    w = 2 * np.pi * f * t + vib
    env = _shaped(t, remain, attack=16.0, decay=0.55) * (f > 0.0)
    return env * _tone(w, (1.0, 0.62, 0.22, 0.08))


def _cello(t, f, remain, _noise):
    vib = 0.45 * np.sin(2 * np.pi * 4.2 * t)
    w = 2 * np.pi * f * t + vib
    env = _shaped(t, remain, attack=8.0, decay=0.35) * (f > 0.0)
    return env * _tone(w, (1.0, 0.7, 0.28, 0.1))


def _flute(t, f, remain, noise):
    vib = 0.35 * np.sin(2 * np.pi * 5.0 * t) * np.clip(t / 0.35, 0.0, 1.0)
    w = 2 * np.pi * f * t + vib
    env = _shaped(t, remain, attack=9.0, decay=0.25) * (f > 0.0)
    breath = noise * 0.14
    return env * (_tone(w, (1.0, 0.12, 0.03)) + breath)


def _horn(t, f, remain, noise):
    w = 2 * np.pi * f * t
    env = _shaped(t, remain, attack=3.2, decay=0.2) * (f > 0.0)
    blat = np.exp(-t * 12.0)
    tone = _tone(w, (1.0, 0.72, 0.38, 0.14))
    return env * (tone + blat * 0.22 * np.sin(5.0 * w))


def _oboe(t, f, remain, noise):
    # Odd harmonics and a short reed chirp. That is the nasal oboe color.
    vib = 0.4 * np.sin(2 * np.pi * 5.2 * t) * np.clip(t / 0.25, 0.0, 1.0)
    w = 2 * np.pi * f * t + vib
    env = _shaped(t, remain, attack=30.0, decay=0.45) * (f > 0.0)
    reed = noise * np.exp(-t * 60.0) * 0.12
    return env * (_tone(w, (1.0, 0.1, 0.72, 0.06, 0.42, 0.04, 0.16)) + reed)


def _timpani(t, f, remain, noise):
    fall = (0.5 * f / 9.0) * (1.0 - np.exp(-9.0 * t))
    phase = 2 * np.pi * (f * t + fall)
    ring = np.exp(-t * 2.4) * np.clip(remain / RELEASE, 0.0, 1.0) * (f > 0.0)
    head = noise * np.exp(-t * 35.0)
    tone = np.sin(phase) + 0.22 * np.sin(2.0 * phase) * np.exp(-t * 6.0)
    return ring * (tone + 0.28 * head)


def proximity_to_volume(prox: int) -> float:
    """Map a proximity count to the master volume, from VOLUME_MIN to VOLUME_MAX."""
    if PROX_NEAR <= PROX_FAR:
        raise ValueError("PROX_NEAR must be greater than PROX_FAR")
    if prox <= PROX_FAR:
        return VOLUME_MIN
    if prox >= PROX_NEAR:
        return VOLUME_MAX
    span = (prox - PROX_FAR) / (PROX_NEAR - PROX_FAR)
    return VOLUME_MIN + span * (VOLUME_MAX - VOLUME_MIN)


class Orchestra:
    """Shared clock. The main loop decides which sections are on, and how loud."""

    def __init__(self) -> None:
        self.want = [False] * len(PARTS)
        self.want[PART_INDEX["viola"]] = True
        self.gain = [0.0] * len(PARTS)
        self.master_target = VOLUME_MIN
        self.master = VOLUME_MIN
        self.n = 0
        self.bar = 0
        self.stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=512,
            callback=self._callback,
        )
        self.stream.start()

    def set_count(self, count: int) -> None:
        """Turn on the first `count` sections in ORDER. Count is already clamped."""
        for i, name in enumerate(ORDER):
            self.want[PART_INDEX[name]] = i < count

    def _callback(self, outdata, frames, _time, status) -> None:
        if status:
            print(status)
        idx = (self.n + np.arange(frames)) % PHRASE
        self.n = (self.n + frames) % PHRASE
        self.bar = int(idx[0] // (EIGHTH * 8))
        noise = np.random.uniform(-1.0, 1.0, frames)

        parts = (
            (_violin, VIOLIN_F, VIOLIN_AGE, VIOLIN_DUR, 0.34),
            (_viola, VIOLA_F, VIOLA_AGE, VIOLA_DUR, 0.30),
            (_cello, CELLO_F, CELLO_AGE, CELLO_DUR, 0.42),
            (_flute, FLUTE_F, FLUTE_AGE, FLUTE_DUR, 0.26),
            (_horn, HORN_F, HORN_AGE, HORN_DUR, 0.36),
            (_timpani, TIMPANI_F, TIMPANI_AGE, TIMPANI_DUR, 0.50),
            (_oboe, OBOE_F, OBOE_AGE, OBOE_DUR, 0.34),
        )
        into = idx % EIGHTH
        mix = np.zeros(frames, dtype=np.float64)
        step_up = 1.0 / int(0.10 * SAMPLE_RATE)
        ramp = np.arange(1, frames + 1)
        for i, (voice, freq, age, dur, level) in enumerate(parts):
            target = 1.0 if self.want[i] else 0.0
            start = self.gain[i]
            if target == 0.0 and start <= 0.0:
                continue
            if target > start:
                gains = np.minimum(start + step_up * ramp, 1.0)
            else:
                gains = np.maximum(start - step_up * ramp, 0.0)
            self.gain[i] = float(gains[-1])
            slot = idx // EIGHTH
            t = (age[slot] * EIGHTH + into) / SAMPLE_RATE
            remain = dur[slot] * EIGHTH - age[slot] * EIGHTH - into
            mix += gains * voice(t, freq[slot], remain, noise) * level

        # master_target is written in the main loop. Glide toward it here.
        master_target = float(self.master_target)
        master_step = 1.0 / int(VOLUME_RAMP_S * SAMPLE_RATE)
        if master_target > self.master:
            masters = np.minimum(self.master + master_step * ramp, master_target)
        else:
            masters = np.maximum(self.master - master_step * ramp, master_target)
        self.master = float(masters[-1])
        outdata[:, 0] = np.clip(mix * 0.72 * masters, -1.0, 1.0).astype(np.float32)

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


def _arrangement(count: int) -> str:
    names = ", ".join(ORDER[:count])
    return f"{count}/{len(ORDER)}  {names}"


def main() -> None:
    if set(ORDER) != set(PARTS):
        raise RuntimeError("ORDER and PARTS must name the same instruments")

    i2c = board.I2C()
    apds = APDS9960(i2c)
    # Gesture mode only runs when proximity is enabled too.
    apds.enable_proximity = True
    apds.enable_gesture = True

    orchestra = Orchestra()
    count = 1
    shown = -1
    last_gesture = 0.0
    last_prox_print = 0.0
    last_prox = -1

    print(f"Proximity orchestra, {BPM} BPM, C major.")
    print("Swipe left to right to add a section. Swipe right to left to remove one.")
    print("Move closer to get louder, and farther away to get quieter.")
    print(
        f"Proximity counts, not centimeters. "
        f"PROX_FAR={PROX_FAR} is quiet, PROX_NEAR={PROX_NEAR} is full."
    )
    print("Edit those two numbers to match the prox lines printed below.")
    print("A hand held close can pause prox updates until the hand moves away.")
    print(_arrangement(count))

    try:
        while True:
            # Sample proximity before gesture(). gesture() can block
            # while a hand is over the sensor.
            prox = apds.proximity
            orchestra.master_target = proximity_to_volume(prox)

            now = time.monotonic()
            if abs(prox - last_prox) >= 4 or now - last_prox_print >= 0.5:
                last_prox = prox
                last_prox_print = now
                print(f"prox {prox:3d}   volume {orchestra.master_target:.2f}")

            # gesture() can sit here until the hand moves away. Time the
            # cooldown from when it returns, so one swipe counts once.
            gesture = apds.gesture()
            now = time.monotonic()
            if gesture in (GESTURE_LEFT, GESTURE_RIGHT) and now - last_gesture >= GESTURE_COOLDOWN_S:
                last_gesture = now
                if gesture == GESTURE_RIGHT and count < len(ORDER):
                    count += 1
                    orchestra.set_count(count)
                    print(f"add  {ORDER[count - 1]}   {_arrangement(count)}")
                elif gesture == GESTURE_LEFT and count > 1:
                    leaving = ORDER[count - 1]
                    count -= 1
                    orchestra.set_count(count)
                    print(f"cut  {leaving}   {_arrangement(count)}")

            bar = orchestra.bar
            if bar != shown:
                shown = bar
                print(f"bar {bar + 1}")
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        orchestra.close()


if __name__ == "__main__":
    main()
