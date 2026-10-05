#!/usr/bin/env python3
"""mini_sheldon.py — mansplainer.py with a British voice and one interruption per turn.

Same stack: Silero VAD, faster-whisper (base.en), Piper (en_GB-semaine-medium).

A short pause still gets talked over, once. After that line he stops. The
next thing you say is one statement: breaths in the middle are not more
facts. When you actually finish, he prints what he heard and only then
arms the next interruption.

    python mini_sheldon.py
    python mini_sheldon.py --listen-silence 1.2   # more room to finish a thought
    python mini_sheldon.py --min-silence 0.15     # ruder first interruption
"""

import argparse
import json
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import sherpa_onnx
import sounddevice as sd
from faster_whisper import WhisperModel
from piper import PiperVoice

SAMPLE_RATE = 16000
LAB_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VAD = LAB_DIR / "models" / "silero_vad.onnx"
DEFAULT_VOICE = LAB_DIR / "voices" / "en_GB-semaine-medium.onnx"


def ensure_voice(path: Path) -> None:
    """Download a Piper voice next to `path` when the onnx file is missing.

    Voice files are gitignored, so a clone on the Pi does not include them.
    """
    if path.is_file():
        return
    name = path.name[:-5] if path.name.endswith(".onnx") else path.name
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Piper voice {name}...", flush=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "piper.download_voices", name,
             "--data-dir", str(path.parent)],
            check=True,
        )
    except subprocess.CalledProcessError:
        sys.exit(
            f"Could not download {name}. With the venv active, from Lab 3:\n"
            f"  python3 -m piper.download_voices {name} --data-dir voices"
        )
    if not path.is_file():
        sys.exit(f"Piper voice still missing at {path}.")

# Sheldon Cooper's usual way in: a correction, then the fact.
# Short on purpose, so --no-transcribe still sounds like him.
OPENERS = [
    "Well, actually.",
    "Actually.",
    "Correction.",
    "Oh. That's interesting.",
    "In point of fact.",
    "Technically.",
    "Allow me to interject.",
    "If I may.",
    "That's incorrect.",
    "A common misconception.",
    "For your information.",
    "I beg to differ.",
    "Permit me to clarify.",
    "As it happens.",
    "Fascinating.",
    "No, no, no.",
    "Excuse me.",
    "I'm going to have to stop you there.",
    "You may find this fascinating.",
    "Bazinga.",
]

# Words that don't carry the point. Dropped so a paraphrase isn't your sentence again.
_STOP = {
    "a", "an", "the", "i", "you", "we", "they", "he", "she", "it", "me", "my",
    "your", "our", "their", "to", "of", "and", "or", "but", "if", "in", "on",
    "for", "with", "at", "from", "as", "is", "are", "was", "were", "be", "been",
    "am", "do", "did", "does", "have", "has", "had", "that", "this", "these",
    "those", "just", "so", "like", "um", "uh", "yeah", "well", "okay", "ok",
    "really", "very", "about", "into", "than", "then", "there", "here", "when",
    "what", "how", "why", "who", "which", "because", "going", "gonna", "wanna",
    "want", "think", "know", "mean", "said", "say", "saying", "im", "i'm", "ive",
    "i've", "id", "i'd", "its", "it's", "dont", "don't", "doesnt", "doesn't",
    "didnt", "didn't", "cant", "can't", "wont", "won't", "isnt", "isn't",
    "wasnt", "wasn't", "youre", "you're", "thats", "that's", "lets", "let's",
    "maybe", "probably", "actually", "basically", "literally", "still", "already",
    "also", "got", "get", "getting", "now", "something", "anything", "everything",
    "nothing", "someone", "everyone", "keep", "keeps", "kept", "make", "makes",
    "not", "no", "yes",
    "should", "could", "would", "can", "will", "shall", "might", "must",
}

_WIKI = "https://en.wikipedia.org/api/rest_v1/page/summary/"
_fact_cache: dict[str, str | None] = {}
_fact_lock = threading.Lock()
_fact_wait: dict[str, threading.Event] = {}

_PARAPHRASES = (
    "The shorter version is that this is about {topic}, and the long version was mostly decoration.",
    "What that actually amounts to is {topic}. The extra detail doesn't change the claim.",
    "You're circling {topic}. That is the whole point, and the rest is scenery.",
    "Strip it down and it's a point about {topic}. The story around it is optional.",
    "The part that matters is {topic}. Everything else was you warming up.",
)

_GENERIC = (
    "There's a shorter way to put that, and it isn't the way you were heading.",
    "The claim under that sentence is smaller than the sentence.",
    "You buried the point. The point was the first concrete thing, and then you kept talking.",
)


def _topic(heard: str) -> str:
    """One or two content words, not a clip of the original sentence."""
    words = re.findall(r"[a-z0-9']+", heard.lower())
    kept = []
    for w in words:
        if w in _STOP or len(w) <= 2 or w in kept:
            continue
        kept.append(w)
    if not kept:
        return ""
    # Longest words are the ones carrying the point. Keep at most two.
    salient = sorted(kept, key=len, reverse=True)[:2]
    if len(salient) == 1:
        return salient[0]
    return f"{salient[0]} and {salient[1]}"


def _keywords(heard: str, limit: int = 3) -> list[str]:
    """Content words worth a Wikipedia lookup, longest first."""
    words = re.findall(r"[a-z0-9']+", heard.lower())
    kept: list[str] = []
    for w in words:
        if w in _STOP or len(w) <= 2 or w in kept:
            continue
        kept.append(w)
    kept.sort(key=len, reverse=True)
    return kept[:limit]


def _wiki_get(url: str, timeout: float) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": "mansplainer-lab/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception:
        return None
    return data


def _fetch_summary(term: str, timeout: float) -> tuple[str | None, str]:
    """Return (first sentence or None, status).

    status is ok, disambiguation, missing, or error. A missing page can be
    cached. A network error cannot, so the next turn tries again.
    """
    url = _WIKI + urllib.parse.quote(term, safe="")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mansplainer-lab/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        return None, "missing" if exc.code == 404 else "error"
    except Exception:
        return None, "error"
    if data.get("type") == "disambiguation":
        return None, "disambiguation"
    extract = (data.get("extract") or "").strip()
    if not extract:
        return None, "missing"
    return re.split(r"(?<=[.!?])\s", extract)[0], "ok"


def _search_titles(term: str, timeout: float) -> list[str]:
    """Other pages for a word whose own summary is a disambiguation list."""
    query = urllib.parse.urlencode({
        "action": "opensearch",
        "search": term,
        "limit": "4",
        "namespace": "0",
        "format": "json",
    })
    data = _wiki_get("https://en.wikipedia.org/w/api.php?" + query, timeout)
    if not isinstance(data, list) or len(data) < 2:
        return []
    return [title for title in data[1] if isinstance(title, str)]


def _resolve(term: str, timeout: float) -> tuple[str | None, bool]:
    """Fact for one word, and whether a miss should be remembered.

    'Stay' is a disambiguation page, so a direct summary comes back empty.
    The search result after it is a real article, and that sentence is used.
    """
    fact, status = _fetch_summary(term, timeout)
    if fact:
        return fact, True
    if status == "error":
        return None, False
    if status == "disambiguation":
        for title in _search_titles(term, timeout):
            if title.casefold() == term.casefold():
                continue
            fact, status = _fetch_summary(title, timeout)
            if fact:
                return fact, True
            if status == "error":
                return None, False
    return None, status == "missing"


def _live_fact(heard: str, timeout: float = 1.2) -> str | None:
    """Opening sentence of a Wikipedia summary for what was just said.

    Tries the longest content words in order. Callers looking up the same
    word share one request.
    """
    for term in _keywords(heard):
        with _fact_lock:
            if term in _fact_cache:
                cached = _fact_cache[term]
                if cached:
                    return cached
                continue
            wait = _fact_wait.get(term)
            if wait is None:
                wait = threading.Event()
                _fact_wait[term] = wait
                owner = True
            else:
                owner = False

        if not owner:
            wait.wait(timeout + 0.3)
            with _fact_lock:
                cached = _fact_cache.get(term)
            if cached:
                return cached
            continue

        fact, cacheable = _resolve(term, timeout)
        with _fact_lock:
            if cacheable:
                _fact_cache[term] = fact
            _fact_wait.pop(term, None)
        wait.set()
        if fact:
            return fact
    return None


def _prefetch(heard: str) -> None:
    """Start the Wikipedia fetch now, so the breath doesn't have to."""
    if not _keywords(heard):
        return
    threading.Thread(target=_live_fact, args=(heard,), daemon=True).start()


def _echoes(heard: str | None, spoken: str) -> bool:
    """True when the mic mostly heard the line we just played."""
    if not heard or not spoken:
        return False
    heard_words = set(re.findall(r"[a-z0-9']+", heard.lower()))
    spoken_words = set(re.findall(r"[a-z0-9']+", spoken.lower()))
    shared = heard_words & spoken_words
    if len(shared) < 3:
        return False
    return len(shared) / min(len(heard_words), len(spoken_words)) >= 0.5


def _paraphrase(heard: str) -> str:
    topic = _topic(heard)
    if not topic:
        return random.choice(_GENERIC)
    return random.choice(_PARAPHRASES).format(topic=topic)


def mansplain(heard: str | None) -> str:
    opener = random.choice(OPENERS)
    if not heard:
        return opener
    body = _live_fact(heard) or _paraphrase(heard)
    return f"{opener} {body}"


def _transcribe(recognizer: WhisperModel, audio: np.ndarray) -> str | None:
    if len(audio) < int(0.15 * SAMPLE_RATE):
        return None
    segments, _ = recognizer.transcribe(
        audio,
        beam_size=1,
        language="en",
        without_timestamps=True,
        condition_on_previous_text=False,
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text or None


class Transcriber:
    """faster-whisper on a side thread, over the words still being said.

    The model decodes a clip; it does not emit a word at a time. Every
    `partial` seconds of new speech we decode the utterance so far and start
    the Wikipedia fetch. When the VAD hears a breath, that line is usually
    already in hand.
    """

    def __init__(self, recognizer: WhisperModel | None, partial: float) -> None:
        self._recognizer = recognizer
        self._partial_n = int(max(partial, 0.3) * SAMPLE_RATE)
        self._cv = threading.Condition()
        self._frames: list[np.ndarray] = []
        self._n = 0
        self._heard: str | None = None
        self._heard_n = 0
        self._job: np.ndarray | None = None
        self._busy = False
        self._busy_gen = -1
        self._gen = 0
        if recognizer is not None:
            threading.Thread(target=self._loop, name="live-whisper", daemon=True).start()

    def extend(self, frame: np.ndarray) -> None:
        if self._recognizer is None or len(frame) == 0:
            return
        with self._cv:
            self._frames.append(np.array(frame, dtype=np.float32, copy=True))
            self._n += len(frame)
            self._schedule_locked()

    def latest(self) -> str | None:
        with self._cv:
            return self._heard

    def has_audio(self) -> bool:
        with self._cv:
            return self._n > 0 or self._heard is not None

    def reset(self) -> None:
        with self._cv:
            self._clear_locked()

    def take(self, final: np.ndarray) -> str | None:
        """Transcript for the utterance that just ended.

        A partial that already landed is used as soon as nothing newer is
        in flight. Otherwise the finished clip is decoded here — that path
        is the short utterance, the one that ended before the first partial.
        """
        if self._recognizer is None:
            return None
        with self._cv:
            # A decode already running has nearly the whole turn. Wait briefly
            # so the breath isn't spent on a clip we meant to finish while
            # they were still talking. Past the grace period, speak anyway.
            self._wait_pending_locked(1.2 if self._heard is None else 0.35)

            if not self._heard and not self._pending_locked():
                audio = np.array(final, dtype=np.float32, copy=True)
                self._frames = [audio]
                self._n = len(audio)
                self._heard_n = 0
                self._job = audio
                self._cv.notify()

            deadline = time.monotonic() + 2.0
            while not self._heard and self._pending_locked() and time.monotonic() < deadline:
                self._cv.wait(timeout=0.05)

            text = self._heard
            self._clear_locked()
            return text

    def _pending_locked(self) -> bool:
        return self._job is not None or (self._busy and self._busy_gen == self._gen)

    def _wait_pending_locked(self, grace: float) -> None:
        if not self._pending_locked():
            return
        deadline = time.monotonic() + grace
        while self._pending_locked() and time.monotonic() < deadline:
            self._cv.wait(timeout=0.05)

    def _schedule_locked(self) -> None:
        if self._busy or self._job is not None:
            return
        if self._n - self._heard_n < self._partial_n or not self._frames:
            return
        self._job = np.concatenate(self._frames)
        self._cv.notify()

    def _clear_locked(self) -> None:
        self._frames = []
        self._n = 0
        self._heard = None
        self._heard_n = 0
        self._job = None
        self._gen += 1
        self._cv.notify_all()

    def _loop(self) -> None:
        assert self._recognizer is not None
        while True:
            with self._cv:
                while self._job is None:
                    self._cv.wait()
                audio = self._job
                gen = self._gen
                end_n = self._n
                self._job = None
                self._busy = True
                self._busy_gen = gen

            try:
                text = _transcribe(self._recognizer, audio)
            except Exception as exc:
                print(f"  (whisper) {exc}", file=sys.stderr)
                text = None

            with self._cv:
                fresh = gen == self._gen
            if text and fresh:
                _prefetch(text)

            with self._cv:
                if gen == self._gen:
                    if text:
                        self._heard = text
                    self._heard_n = end_n
                self._busy = False
                if gen == self._gen:
                    self._schedule_locked()
                self._cv.notify_all()


class Speaker:
    """Piper TTS -> default output device. Lifted from echo_bot.py, with an
    added cache so canned openers play back instantly instead of re-synthesizing."""

    def __init__(self, voice_path: Path) -> None:
        self.voice = PiperVoice.load(str(voice_path))

    def say(self, text: str) -> None:
        for chunk in self.voice.synthesize(text):
            audio = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
            sd.play(audio, samplerate=chunk.sample_rate)
            sd.wait()


def _discard_input(stream: sd.InputStream) -> None:
    """Throw away audio recorded while the speaker was playing.

    The mic stays open during playback, so the next read would otherwise be
    Sheldon's own line, and the following 'fact' would be about that.
    """
    time.sleep(0.2)
    for _ in range(6):
        available = stream.read_available
        if available <= 0:
            break
        stream.read(available)
        time.sleep(0.05)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="base.en",
                        help="whisper model size (default: base.en)")
    parser.add_argument("--vad-model", type=Path, default=DEFAULT_VAD)
    parser.add_argument("--voice", type=Path, default=DEFAULT_VOICE)
    parser.add_argument("--min-silence", type=float, default=0.2,
                        help="silence that triggers the interruption (default: 0.2)")
    parser.add_argument("--listen-silence", type=float, default=0.9,
                        help="quiet that ends the statement after an interruption (default: 0.9)")
    parser.add_argument("--min-speech", type=float, default=0.25,
                        help="ignore speech bursts shorter than this (default: 0.25)")
    parser.add_argument("--partial", type=float, default=0.5,
                        help="seconds of new speech between live transcriptions (default: 0.5)")
    parser.add_argument("--no-transcribe", action="store_true",
                        help="skip whisper entirely; canned interrupts only")
    args = parser.parse_args()
    ensure_voice(args.voice)

    for path, what in [(args.vad_model, "VAD model"), (args.voice, "Piper voice")]:
        if not path.is_file():
            sys.exit(f"{what} not found at {path}. Run ./setup.sh first.")

    print("Loading models...", flush=True)
    speaker = Speaker(args.voice)
    recognizer = None if args.no_transcribe else \
        WhisperModel(args.model, device="cpu", compute_type="int8")
    ear = Transcriber(recognizer, args.partial)

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(args.vad_model)
    config.silero_vad.min_silence_duration = args.min_silence
    config.silero_vad.min_speech_duration = args.min_speech
    config.sample_rate = SAMPLE_RATE
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
    window = config.silero_vad.window_size

    if not hasattr(vad, "is_speech_detected"):
        sys.exit("This sherpa-onnx build has no VAD.is_speech_detected(); "
                 "upgrade sherpa-onnx to 1.10 or newer.")

    # After a fact, breaths inside the reply are not new turns. This is how
    # much extra quiet, on top of --min-silence, means the statement is over.
    statement_gap = max(0.05, args.listen_silence - args.min_silence)

    print(f"Ready. I'll jump in after {args.min_silence}s, then listen "
          f"until you've been quiet for {args.listen_silence}s. Ctrl-C to stop.\n")

    buffer = np.empty(0, dtype=np.float32)
    samples_per_read = int(0.1 * SAMPLE_RATE)
    shown: str | None = None
    listening = False
    statement: list[np.ndarray] = []
    tail_silence = 0.0
    last_reply = ""

    with sd.InputStream(channels=1, dtype="float32", samplerate=SAMPLE_RATE) as stream:
        while True:
            chunk, _ = stream.read(samples_per_read)
            buffer = np.concatenate([buffer, chunk.reshape(-1)])

            while len(buffer) > window:
                frame = buffer[:window]
                buffer = buffer[window:]
                vad.accept_waveform(frame)
                speaking = vad.is_speech_detected()

                if recognizer is not None and speaking:
                    ear.extend(frame)
                    tail_silence = 0.0
                elif ear.has_audio() and vad.empty() and not listening:
                    # A blip too short to be a turn. Drop it so the next
                    # sentence is transcribed on its own.
                    ear.reset()
                    shown = None

                if listening and statement and not speaking and vad.empty():
                    tail_silence += len(frame) / SAMPLE_RATE

            live = ear.latest()
            if live and live != shown:
                shown = live
                print(f"  (hearing) {live}", flush=True)

            while not vad.empty():
                utterance = np.array(vad.front.samples, dtype=np.float32)
                vad.pop()

                if listening:
                    # Hold the reply together across breaths. No new fact.
                    statement.append(utterance)
                    tail_silence = 0.0
                    continue

                heard = ear.take(utterance)
                if _echoes(heard, last_reply):
                    ear.reset()
                    shown = None
                    continue

                reply = mansplain(heard)
                print(f"  (you paused) -> {reply}", flush=True)
                speaker.say(reply)
                last_reply = reply
                _discard_input(stream)

                while not vad.empty():
                    vad.pop()
                buffer = np.empty(0, dtype=np.float32)
                ear.reset()
                shown = None
                statement = []
                tail_silence = 0.0
                listening = True
                print("  (your turn - I'll wait until you finish)", flush=True)

            if listening and statement and tail_silence >= statement_gap:
                heard = ear.take(np.concatenate(statement))
                if _echoes(heard, last_reply):
                    print("  (that was me, still listening)", flush=True)
                    statement = []
                    tail_silence = 0.0
                    ear.reset()
                    shown = None
                    buffer = np.empty(0, dtype=np.float32)
                    while not vad.empty():
                        vad.pop()
                    continue
                print(f"  (heard you) {heard or '(nothing intelligible)'}", flush=True)
                statement = []
                tail_silence = 0.0
                listening = False
                ear.reset()
                shown = None
                buffer = np.empty(0, dtype=np.float32)
                while not vad.empty():
                    vad.pop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nFinally, some peace.")
