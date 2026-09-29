#!/usr/bin/env python3
"""mansplainer.py — a sibling of echo_bot.py that never lets you finish a thought.

Same stack as listen.py / echo_bot.py:
  - sherpa_onnx Silero VAD for endpointing
  - faster-whisper for (optional) transcription
  - Piper for speech out

The trick is the endpointing threshold. Crank --min-silence way down: the VAD
then emits your utterance the instant you take a breath, and we pounce before
you can continue. If you named something we know, the reply is a fun fact
about it. Otherwise it paraphrases the point instead of quoting you.

    python mansplainer.py                    # pounces after 0.2s of silence
    python mansplainer.py --min-silence 0.15 # insufferable
    python mansplainer.py --no-transcribe    # pure canned interrupts, zero ASR lag
"""

import argparse
import random
import re
import sys
from pathlib import Path

import numpy as np
import sherpa_onnx
import sounddevice as sd
from faster_whisper import WhisperModel
from piper import PiperVoice

SAMPLE_RATE = 16000
LAB_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VAD = LAB_DIR / "models" / "silero_vad.onnx"
DEFAULT_VOICE = LAB_DIR / "voices" / "en_US-lessac-medium.onnx"

# Canned openers, played the instant you pause. These carry the joke on their
# own, so the device still works with --no-transcribe.
OPENERS = [
    "Fun fact.",
    "Let me just chime in.",
    "Not to be the devil's advocate.",
    "Well, actually.",
    "Okay, so, let me break this down for you.",
    "Right, but here's the thing most people miss.",
    "Actually, it's a little more nuanced than that.",
    "Sorry, real quick.",
    "I don't mean to interrupt.",
    "Hold on, this is the interesting part.",
    "Since you brought it up.",
    "Funny you should say that.",
    "Quick sidebar.",
    "Before you finish that thought.",
    "That's adjacent to a better point.",
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
    "should", "could", "would", "can", "will", "shall", "might", "must",
}

# Longer keys first so "new york" wins over a shorter overlap.
FUN_FACTS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("new york", "nyc", "manhattan"), (
        "The first New York subway line opened in 1904 and was only about nine miles long.",
        "Manhattan's street grid was drawn in 1811, which is why the avenues ignore the old village paths.",
    )),
    (("subway", "train", "metro"), (
        "The word subway and the word metro name the same idea. Metro is short for metropolitan railway.",
        "The busiest subway systems move more people in a day than many airlines move in a year.",
    )),
    (("coffee", "espresso", "latte", "caffeine"), (
        "Coffee was eaten before it was brewed. People in Ethiopia mixed the berries with fat.",
        "Decaf coffee was an accident. A shipment got soaked in seawater, and the beans had lost their caffeine.",
    )),
    (("tea",), (
        "Tea bags were a packaging accident. A merchant sent samples in silk pouches, and people brewed the pouch.",
        "A cup of tea steeps better with cooler water than people use. Boiling water burns green tea.",
    )),
    (("pizza",), (
        "Pizza margherita was named in 1889 for Queen Margherita, using the red, white, and green of the Italian flag.",
        "The tomato sat on the table in Europe for a long time as an ornamental plant before anyone trusted it on bread.",
    )),
    (("banana", "bananas"), (
        "A banana is a berry. A strawberry is not. Berries, botanically, come from one flower with one ovary.",
        "The bananas in stores are almost all one clone, Cavendish, which is why a single disease can threaten the crop.",
    )),
    (("apple", "apples"), (
        "Apples float because about a quarter of their volume is air.",
        "The apple you buy is a clone. Every Honeycrisp is a cutting from an older tree, not a new seedling.",
    )),
    (("honey",), (
        "Honey does not spoil. Jars from Egyptian tombs were still edible thousands of years later.",
    )),
    (("food", "hungry", "lunch", "dinner", "breakfast"), (
        "Taste is mostly smell. Pinch your nose and an apple and a potato are hard to tell apart.",
    )),
    (("dog", "dogs", "puppy"), (
        "A dog's nose print is unique, the way a fingerprint is.",
        "Dogs can hear about twice as high a pitch as people can, which is why a silent whistle is only silent to you.",
    )),
    (("cat", "cats", "kitten"), (
        "Cats sleep about seventy percent of their lives. The nap you are watching is the default state.",
        "A cat's purr sits at a frequency that can promote bone healing. It is not only a mood.",
    )),
    (("sleep", "tired", "nap"), (
        "You cannot fully bank sleep. An all-nighter is not repaid by one long morning.",
        "Dolphins sleep with one half of the brain at a time, so they can keep surfacing to breathe.",
    )),
    (("phone", "iphone", "text", "texting"), (
        "The first text message was sent in 1992. It said merry christmas.",
        "Early mobile phones were called bricks because the battery was most of the object.",
    )),
    (("computer", "laptop", "keyboard"), (
        "The first computer bug was a real moth, found in a Harvard relay in 1947 and taped into the logbook.",
    )),
    (("wifi", "internet", "wi-fi"), (
        "Wi-Fi does not officially stand for wireless fidelity. The name was a brand, picked to sound like hi-fi.",
        "The first message sent over the internet's ancestor was supposed to be login. The system crashed after lo.",
    )),
    (("ai", "robot", "chatgpt"), (
        "The word robot comes from the Czech robota, meaning forced labor. It showed up in a 1920 play.",
        "Most of what people call artificial intelligence is pattern matching at a huge scale, not a stored list of facts.",
    )),
    (("music", "song", "spotify"), (
        "An earworm sticks because the brain keeps predicting the next note and won't close the loop.",
        "The same song feels faster when you are anxious. Tempo did not change. Your clock did.",
    )),
    (("rain", "raining", "weather"), (
        "The smell of rain has a name, petrichor. It is oils from plants plus a compound from soil bacteria.",
        "Raindrops are not tear-shaped. They fall as flattened spheres, wider than they are tall.",
    )),
    (("cornell", "ithaca"), (
        "Cornell was founded in 1865. Ezra Cornell's line was that he would found an institution where any person can find instruction in any study.",
    )),
    (("school", "class", "homework", "lecture"), (
        "The word school comes from the Greek skhole, which meant leisure. Study was what you did with free time.",
    )),
    (("time", "clock", "hour"), (
        "A day is not exactly twenty-four hours. Earth takes about four minutes longer to spin once than a civil clock admits.",
        "Leap seconds exist because the planet's spin does not match the atomic clocks we actually keep time with.",
    )),
    (("water",), (
        "You can drink too much water. The danger is diluting the sodium in your blood, not the water itself.",
    )),
    (("moon",), (
        "The Moon is moving away from Earth by a little under four centimeters a year.",
        "The same side of the Moon always faces Earth because its spin and its orbit take the same amount of time.",
    )),
    (("money", "dollar", "cash"), (
        "The dollar sign probably comes from a written abbreviation of pesos, not from a drawing of a pillar.",
    )),
]

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


def _fun_fact(heard: str) -> str | None:
    text = heard.lower()
    hits: list[str] = []
    for keys, facts in FUN_FACTS:
        if any(re.search(rf"\b{re.escape(key)}\b", text) for key in keys):
            hits.extend(facts)
    if not hits:
        return None
    return random.choice(hits)


def _paraphrase(heard: str) -> str:
    topic = _topic(heard)
    if not topic:
        return random.choice(_GENERIC)
    return random.choice(_PARAPHRASES).format(topic=topic)


def mansplain(heard: str | None) -> str:
    opener = random.choice(OPENERS)
    if not heard:
        return opener
    body = _fun_fact(heard) or _paraphrase(heard)
    return f"{opener} {body}"


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="tiny.en", help="whisper model size")
    parser.add_argument("--vad-model", type=Path, default=DEFAULT_VAD)
    parser.add_argument("--voice", type=Path, default=DEFAULT_VOICE)
    parser.add_argument("--min-silence", type=float, default=0.2,
                        help="silence that ends your turn; low = rude (default: 0.2)")
    parser.add_argument("--min-speech", type=float, default=0.25,
                        help="ignore speech bursts shorter than this (default: 0.25)")
    parser.add_argument("--no-transcribe", action="store_true",
                        help="skip whisper entirely; canned interrupts only")
    args = parser.parse_args()

    for path, what in [(args.vad_model, "VAD model"), (args.voice, "Piper voice")]:
        if not path.is_file():
            sys.exit(f"{what} not found at {path}. Run ./setup.sh first.")

    print("Loading models...", flush=True)
    speaker = Speaker(args.voice)
    recognizer = None if args.no_transcribe else \
        WhisperModel(args.model, device="cpu", compute_type="int8")

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(args.vad_model)
    config.silero_vad.min_silence_duration = args.min_silence
    config.silero_vad.min_speech_duration = args.min_speech
    config.sample_rate = SAMPLE_RATE
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
    window = config.silero_vad.window_size

    print(f"Ready. Try to say something (I pounce after {args.min_silence}s). Ctrl-C to stop.\n")

    buffer = np.empty(0, dtype=np.float32)
    samples_per_read = int(0.1 * SAMPLE_RATE)

    with sd.InputStream(channels=1, dtype="float32", samplerate=SAMPLE_RATE) as stream:
        while True:
            chunk, _ = stream.read(samples_per_read)
            buffer = np.concatenate([buffer, chunk.reshape(-1)])

            while len(buffer) > window:
                vad.accept_waveform(buffer[:window])
                buffer = buffer[window:]

            while not vad.empty():
                utterance = np.array(vad.front.samples, dtype=np.float32)
                vad.pop()

                heard = None
                if recognizer is not None:
                    segments, _ = recognizer.transcribe(utterance, beam_size=1)
                    heard = " ".join(s.text.strip() for s in segments).strip() or None

                reply = mansplain(heard)
                print(f"  (you paused) -> {reply}")
                speaker.say(reply)

                # Drop anything the mic caught while we were talking, so the
                # device doesn't interrupt its own interruption.
                while not vad.empty():
                    vad.pop()
                buffer = np.empty(0, dtype=np.float32)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nFinally, some peace.")
