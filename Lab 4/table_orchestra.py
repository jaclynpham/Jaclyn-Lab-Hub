"""One table, one speaker, three sensors, all in A minor.

The piece is the house beat from twizzler_dj.py. It loops at 120 BPM.
Timpani, hats, clap, bass, chord, and arp stay on the same bar.

Sitting down. The Qwiic VCNL4040 watches the place setting. A higher
reading means closer. The groove fades up as someone leans in:

    far                  silence
    bass
    bass + chord
    bass + chord + timpani

That bed also gets louder as the reading rises. At startup the script
reads the empty table and stays silent until someone raises the count
above that. The servo gets no pulse until that same detection. While
someone is in range it sweeps the way servo_test.py does, and the
pulse is released again when they leave. The count is not centimeters.

Touch. Six conductive objects on the MPR121. Holding one plays that
part at full level. Letting go fades only that part. Bass and timpani
also join when someone sits close, and stay if the pad is still held
after they lean away.

    pad 1    timpani
    pad 3    hats
    pad 5    clap
    pad 6    bass
    pad 8    chord
    pad 10   arp

Notes written below middle C are played one or two octaves higher, in the
same key, so a small speaker can produce them. The timpani is tuned to A.

The bowl. The APDS-9960 sits under one object, looking up. Its resting
reading is measured at startup, and the drone stays silent until a
hand raises it. A hand hovering there rings an A minor drone (A, C, E),
so it sits in the same chord as the beat. Moving the hand around the
object shifts which harmonic is bright, the way a mallet wakes a singing
bowl by circling the rim. Closer to the opening is louder. The tone keeps
ringing for a moment after the hand leaves.

All of this is mixed in one audio callback. The callback never reads
a sensor.
"""

import math
import time

import board
import numpy as np
import sounddevice as sd
import adafruit_mpr121
import qwiic_proximity
from adafruit_apds9960.apds9960 import APDS9960
from adafruit_servokit import ServoKit

import twizzler_dj as deck

# 1.0 is full scale, the "volume 100" level.
MASTER = 1.0
# Small speakers fade out under middle C. Notes below this are doubled
# until they clear it. C stays C, so the harmony does not change.
SPEAKER_FLOOR = 261.63

# Qwiic proximity counts. Higher means closer.
# The empty table is measured at startup. Harmony and the servo stay
# off until the reading rises above that resting count by QWIIC_MARGIN.
# QWIIC_SPAN counts past that point bring in the full bed.
QWIIC_MARGIN = 30
QWIIC_SPAN = 180
# Groove that arrives as someone sits down, in that order.
BED = ("bass", "chord", "kick")
# Same hat, channel, and pulse range as servo_test.py.
# angle None sends no pulse, so the servo stays still.
# A Qwiic detection starts the 180 / 0 sweep. Leaving releases it again.
SERVO_CHANNEL = 2
SERVO_SWEEP_S = 2.0
# Adafruit proximity is 0–255. The resting count is measured at startup.
# The bowl stays silent until a hand raises it by at least APDS_MARGIN.
APDS_MARGIN = 8
APDS_SPAN = 40

# MPR121 pad, then the part it plays while held.
TOUCH = (
    (1, "kick"),
    (3, "hats"),
    (5, "clap"),
    (6, "bass"),
    (8, "chord"),
    (10, "arp"),
)
# Same mix levels as twizzler_dj.py, in PARTS order.
LEVELS = (0.9, 0.35, 0.55, 0.45, 0.4, 0.28)

# APDS-9960 photodiode sums. The bowl uses these, not gesture() directions.
# A rise above the resting sum also counts as a hand over the object.
BOWL_MIN = 30
BOWL_ENERGY_MARGIN = 50
BOWL_ENERGY_SPAN = 250
BOWL_HOLD_S = 0.20
BOWL_ATTACK_S = 0.30
BOWL_RELEASE_S = 1.80
# A minor partials, from the DJ stab. The root is lifted one octave.
_ROOT = deck.STAB[0] * 2
BOWL_FREQS = (_ROOT, _ROOT * 3 / 2, _ROOT * 2, _ROOT * 12 / 5)
BOWL_NAMES = ("fundamental", "fifth", "octave", "third")

# Gesture FIFO registers. gesture() would block until the hand left and
# would throw these four counts away, so the bowl reads the FIFO itself.
_GFLVL = 0xAE
_GSTATUS = 0xAF
_GFOV = 0x02
_GCONF4 = 0xAB
_GFIFO_CLR = 0x04
_GFIFO_U = 0xFC


def _audible(span: float) -> float:
    """A detected hand starts at a level the speaker can actually play."""
    if span <= 0.0:
        return 0.0
    if span >= 1.0:
        return 1.0
    return 0.62 + 0.38 * span


def bed_state(prox: float, floor: float) -> tuple[int, float]:
    """How many bed parts are on, and how loud the bed is, from one proximity count.

    floor is the empty-table count. At or below it, the bed is silent.
    """
    if prox <= floor:
        return 0, 0.0
    span = min(prox - floor, QWIIC_SPAN) / QWIIC_SPAN
    count = int(span * len(BED)) + 1
    if count > len(BED):
        count = len(BED)
    return count, _audible(span)


def apds_level(prox: int, floor: float) -> float:
    """Bowl loudness from the Adafruit proximity count, before any circle data.

    floor is the resting count with the object in place. At or below it,
    the bowl is silent.
    """
    if prox <= floor:
        return 0.0
    span = min(prox - floor, APDS_SPAN) / APDS_SPAN
    return _audible(span)


def bowl_from_diodes(up: float, down: float, left: float, right: float, energy_floor: float):
    """Volume and four harmonic weights from one hover around the object.

    Returns None when the hand is not over the opening. The fundamental
    stays present. Circling crossfades the fifth, octave, and third.
    """
    energy = up + down + left + right
    if energy <= energy_floor:
        return None
    span = min(energy - energy_floor, BOWL_ENERGY_SPAN) / BOWL_ENERGY_SPAN
    level = _audible(span)
    x = right - left
    y = up - down
    if math.hypot(x, y) < 12:
        weights = (1.0, 0.22, 0.16, 0.12)
    else:
        angle = math.atan2(y, x)
        fifth = 0.12 + 0.55 * (0.5 + 0.5 * math.cos(angle))
        octave = 0.12 + 0.55 * (0.5 + 0.5 * math.cos(angle - 2.094395))
        third = 0.08 + 0.42 * (0.5 + 0.5 * math.cos(angle + 2.094395))
        weights = (1.0, fifth, octave, third)
    return level, weights


def _in_speaker_range(freq: np.ndarray) -> np.ndarray:
    """Move sounding notes up by octaves until they clear SPEAKER_FLOOR."""
    out = np.asarray(freq, dtype=np.float64).copy()
    for _ in range(3):
        low = (out > 0.0) & (out < SPEAKER_FLOOR)
        if not np.any(low):
            break
        out = np.where(low, out * 2.0, out)
    return out


def _bass_line(t, eighth):
    """The DJ bass line, raised until a small speaker can play it."""
    freq = _in_speaker_range(deck.BASS[eighth])
    env = np.exp(-t * 6) * (freq > 0)
    w = 2 * np.pi * freq * t
    return env * (np.sin(w) + 0.4 * np.sin(2 * w) + 0.15 * np.sin(3 * w))


def _chord_stab(t, eighth):
    """The A minor stab, with the low root lifted."""
    on = (eighth == 1) | (eighth == 5)
    env = np.exp(-t * 9) * on
    tones = _in_speaker_range(np.asarray(deck.STAB, dtype=np.float64))
    tone = sum(np.sin(2 * np.pi * freq * t) for freq in tones)
    return env * tone / 3


def _timpani_hit(t, noise):
    """A struck drum tuned to A4, with a mallet attack and a short ring.

    The old kick lived near 48 Hz, under what this speaker can play.
    """
    pitch = 440.0
    drop = (pitch * 0.1) * (1.0 - np.exp(-16.0 * t))
    phase = 2 * np.pi * (pitch * t - drop)
    ring = np.exp(-t * 8.0)
    head = np.sin(1.9 * phase) * np.exp(-t * 14.0)
    mallet = noise * np.exp(-t * 50.0)
    tick = np.sin(2 * np.pi * 1500.0 * t) * np.exp(-t * 70.0)
    return ring * (np.sin(phase) + 0.4 * head) + 0.5 * mallet + 0.18 * tick


def _layer(index, t_beat, t_eighth, t_step, beat, eighth, step, noise):
    if index == 0:
        return _timpani_hit(t_beat, noise)
    if index == 1:
        return deck._hats(t_eighth, eighth, noise)
    if index == 2:
        return deck._clap(t_beat, beat, noise)
    if index == 3:
        return _bass_line(t_eighth, eighth)
    if index == 4:
        return _chord_stab(t_eighth, eighth)
    return deck._arp(t_step, step)


def _glide(start: float, target: float, frames: int, seconds: float) -> tuple[np.ndarray, float]:
    step = 1.0 / max(1, int(seconds * deck.SAMPLE_RATE))
    ramp = np.arange(1, frames + 1)
    if target >= start:
        values = np.minimum(start + step * ramp, target)
    else:
        values = np.maximum(start - step * ramp, target)
    return values, float(values[-1])


def _read8(device, register: int) -> int:
    buf = bytearray(2)
    buf[0] = register
    with device as i2c:
        i2c.write_then_readinto(buf, buf, out_end=1, in_end=1)
    return buf[0]


def _set_bit(device, register: int, mask: int) -> None:
    buf = bytearray(2)
    buf[0] = register
    with device as i2c:
        i2c.write_then_readinto(buf, buf, out_end=1, in_start=1)
    buf[0] = register
    buf[1] |= mask
    with device as i2c:
        i2c.write(buf, end=2)


def read_diodes(device):
    """Average up, down, left, right counts, or None if the hand is away."""
    if _read8(device, _GSTATUS) & _GFOV:
        _set_bit(device, _GCONF4, _GFIFO_CLR)
        return None
    level = _read8(device, _GFLVL)
    if level <= 0:
        return None
    count = min(level, 32)
    buf = bytearray(1 + count * 4)
    buf[0] = _GFIFO_U
    with device as i2c:
        i2c.write_then_readinto(buf, buf, out_end=1, in_start=1, in_end=1 + count * 4)
    sums = [0.0, 0.0, 0.0, 0.0]
    used = 0
    for i in range(count):
        sample = [buf[1 + i * 4 + k] for k in range(4)]
        if sample == [255, 255, 255, 255]:
            continue
        if sum(sample) < BOWL_MIN:
            continue
        for k in range(4):
            sums[k] += sample[k]
        used += 1
    if used == 0:
        return None
    return tuple(value / used for value in sums)


class Orchestra:
    """Shared clock. Sensors only set targets. This mixes them."""

    def __init__(self) -> None:
        n = len(deck.PARTS)
        self.touch_on = [False] * n
        self.bed_on = [False] * n
        self.touch_gain = [0.0] * n
        self.bed_gain = [0.0] * n
        self.bed_level = 0.0
        self.bed_target = 0.0
        self.bowl_level = 0.0
        self.bowl_target = 0.0
        self.bowl_weights = [0.0, 0.0, 0.0, 0.0]
        self.bowl_targets = (1.0, 0.2, 0.15, 0.1)
        self.n = 0
        self.samples = 0
        self.stream = sd.OutputStream(
            samplerate=deck.SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=512,
            callback=self._callback,
        )
        self.stream.start()

    def _callback(self, outdata, frames, _time, status) -> None:
        if status:
            print(status)
        pos = (self.n + np.arange(frames)) % deck.BAR
        self.n = (self.n + frames) % deck.BAR
        t_beat = (pos % deck.BEAT) / deck.SAMPLE_RATE
        beat = (pos * 4) // deck.BAR
        eighth = (pos * 8) // deck.BAR
        step = (pos * 16) // deck.BAR
        t_eighth = (pos - (eighth * deck.BAR) // 8) / deck.SAMPLE_RATE
        t_step = (pos - (step * deck.BAR) // 16) / deck.SAMPLE_RATE
        noise = np.random.uniform(-1.0, 1.0, frames)
        mix = np.zeros(frames, dtype=np.float64)
        step_up = 1.0 / int(0.02 * deck.SAMPLE_RATE)
        ramp = np.arange(1, frames + 1)
        bed_env, self.bed_level = _glide(self.bed_level, self.bed_target, frames, 0.25)
        for i in range(len(deck.PARTS)):
            touch_target = 1.0 if self.touch_on[i] else 0.0
            bed_part_target = 1.0 if self.bed_on[i] else 0.0
            if (
                touch_target == 0.0
                and self.touch_gain[i] <= 0.0
                and bed_part_target == 0.0
                and self.bed_gain[i] <= 0.0
            ):
                continue
            if touch_target > self.touch_gain[i]:
                touch_g = np.minimum(self.touch_gain[i] + step_up * ramp, 1.0)
            else:
                touch_g = np.maximum(self.touch_gain[i] - step_up * ramp, 0.0)
            self.touch_gain[i] = float(touch_g[-1])
            if bed_part_target > self.bed_gain[i]:
                bed_g = np.minimum(self.bed_gain[i] + step_up * ramp, 1.0)
            else:
                bed_g = np.maximum(self.bed_gain[i] - step_up * ramp, 0.0)
            self.bed_gain[i] = float(bed_g[-1])
            if deck.PARTS[i] in BED:
                gains = np.maximum(touch_g, bed_g * bed_env)
            else:
                gains = touch_g
            layer = _layer(i, t_beat, t_eighth, t_step, beat, eighth, step, noise)
            mix += gains * layer * LEVELS[i]

        bowl_seconds = BOWL_ATTACK_S if self.bowl_target >= self.bowl_level else BOWL_RELEASE_S
        bowl_env, self.bowl_level = _glide(self.bowl_level, self.bowl_target, frames, bowl_seconds)
        targets = self.bowl_targets
        for k in range(len(BOWL_FREQS)):
            self.bowl_weights[k] += (float(targets[k]) - self.bowl_weights[k]) * 0.2
        if self.bowl_level > 0.0008:
            bt = (self.samples + np.arange(frames)) / deck.SAMPLE_RATE
            tone = np.zeros(frames, dtype=np.float64)
            for k, freq in enumerate(BOWL_FREQS):
                tone += self.bowl_weights[k] * np.sin(2 * np.pi * freq * bt)
            mix += tone * bowl_env * 0.42
        self.samples += frames
        outdata[:, 0] = np.clip(mix * MASTER, -1.0, 1.0).astype(np.float32)

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


def _shown(name: str) -> str:
    if name == "kick":
        return "timpani"
    return name


def _bed_names(count: int) -> str:
    if count <= 0:
        return "silence"
    return " + ".join(_shown(name) for name in BED[:count])


def main() -> None:
    touch_names = {name for _, name in TOUCH}
    if not touch_names <= set(deck.PARTS) or not set(BED) <= set(deck.PARTS):
        raise RuntimeError("Every part must come from the orchestra")

    i2c = board.I2C()
    mpr121 = adafruit_mpr121.MPR121(i2c)
    apds = APDS9960(i2c)
    apds.enable_proximity = True
    apds.proximity_gain = 3
    apds.gesture_gain = 3
    apds.enable_gesture = True

    qwiic = qwiic_proximity.QwiicProximity()
    if not qwiic.connected:
        raise RuntimeError("Qwiic proximity sensor not found. Check the Qwiic cable.")
    qwiic.begin()

    print("Step back from the Qwiic sensor, and leave the bowl object as it sits.")
    resting_samples = []
    apds_samples = []
    energy_samples = []
    for _ in range(8):
        resting_samples.append(float(qwiic.get_proximity()))
        apds_samples.append(int(apds.proximity))
        diodes = read_diodes(apds.i2c_device)
        if diodes is not None:
            energy_samples.append(sum(diodes))
        time.sleep(0.05)
    qwiic_floor = max(resting_samples) + QWIIC_MARGIN
    apds_floor = max(apds_samples) + APDS_MARGIN
    energy_floor = (max(energy_samples) if energy_samples else float(BOWL_MIN)) + BOWL_ENERGY_MARGIN
    print(
        f"Empty Qwiic reading {max(resting_samples):.0f}. "
        f"Harmony starts above {qwiic_floor:.0f}."
    )
    print(
        f"Resting proximity {max(apds_samples)}. "
        f"Bowl starts above {apds_floor:.0f}."
    )

    kit = ServoKit(channels=16, i2c=i2c)
    servo = kit.servo[SERVO_CHANNEL]
    servo.set_pulse_width_range(500, 2500)
    servo.angle = None

    part_index = {name: i for i, name in enumerate(deck.PARTS)}
    orchestra = Orchestra()
    held = {pad: False for pad, _ in TOUCH}
    bed_count = 0
    prox_smooth = 0.0
    last_prox_print = -9999.0
    last_apds_print = -1
    bowl_on = False
    bowl_color = ""
    last_bowl = 0.0
    servo_spinning = False
    servo_high = False
    servo_step_at = 0.0

    print(f"Table orchestra, house beat, {deck.BPM} BPM, A minor. One speaker.")
    print("Lean in. The Qwiic sensor adds the harmony, raises its volume, and only then moves the servo.")
    print(f"  far  <= {qwiic_floor:.0f}   silence")
    print(f"  near >= {qwiic_floor + QWIIC_SPAN:.0f}  {_bed_names(len(BED))}")
    print("Touch an object to add that line. Let go to fade it.")
    for pad, name in TOUCH:
        print(f"  pad {pad}  {_shown(name)}")
    print("Circle a hand over the bowl object. Closer is louder. It rings after you leave.")

    try:
        while True:
            now = time.monotonic()
            prox = float(qwiic.get_proximity())
            prox_smooth += (prox - prox_smooth) * 0.12
            count, level = bed_state(prox_smooth, qwiic_floor)
            orchestra.bed_target = level
            if count > 0:
                if not servo_spinning:
                    servo_spinning = True
                    servo_high = True
                    servo.angle = 180
                    servo_step_at = now
                    print("servo spin")
                elif now - servo_step_at >= SERVO_SWEEP_S:
                    servo_high = not servo_high
                    servo.angle = 180 if servo_high else 0
                    servo_step_at = now
            elif servo_spinning:
                servo_spinning = False
                servo.angle = None
                print("servo stop")
            if count != bed_count:
                for i, name in enumerate(BED):
                    orchestra.bed_on[part_index[name]] = i < count
                bed_count = count
                print(f"qwiic {prox_smooth:.0f}   {_bed_names(count)}")
                last_prox_print = prox_smooth
            elif abs(prox_smooth - last_prox_print) >= 15:
                last_prox_print = prox_smooth
                print(f"qwiic {prox_smooth:.0f}   {_bed_names(count)}")

            for pad, name in TOUCH:
                down = bool(mpr121[pad].value)
                if down and not held[pad]:
                    held[pad] = True
                    orchestra.touch_on[part_index[name]] = True
                    print(f"cue  {pad} {name}")
                elif not down and held[pad]:
                    held[pad] = False
                    orchestra.touch_on[part_index[name]] = False
                    print(f"cut  {pad} {name}")

            diodes = read_diodes(apds.i2c_device)
            hover = apds_level(apds.proximity, apds_floor)
            heard = None if diodes is None else bowl_from_diodes(*diodes, energy_floor)
            if heard is None and hover <= 0.0:
                if bowl_on and now - last_bowl > BOWL_HOLD_S:
                    bowl_on = False
                    orchestra.bowl_target = 0.0
                    print("bowl rings out")
            else:
                last_bowl = now
                if heard is None:
                    closeness = hover
                    weights = (1.0, 0.35, 0.25, 0.2)
                else:
                    closeness, weights = heard
                    closeness = max(closeness, hover)
                orchestra.bowl_target = closeness
                orchestra.bowl_targets = weights
                if not bowl_on:
                    bowl_on = True
                    print(f"bowl  apds {apds.proximity}")
                elif abs(apds.proximity - last_apds_print) >= 8:
                    last_apds_print = apds.proximity
                    print(f"apds {apds.proximity}   bowl {closeness:.2f}")
                color = BOWL_NAMES[1 + max(range(3), key=lambda k: weights[k + 1])]
                if color != bowl_color and closeness > 0.7:
                    bowl_color = color
                    print(f"bowl {color}")

            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        servo.angle = None
        time.sleep(0.5)
        orchestra.close()


if __name__ == "__main__":
    main()
