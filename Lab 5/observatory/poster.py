"""Morning poster. Observations, ASCII artwork, and Qwen notes stay distinct.

Layout, scale, and colors come from random.Random(seed). The default seed is
the session record, so a rerender matches unless --seed is set. Colors are
full rgb(r, g, b) channels from 0 to 255. The HTML file has no remote assets.
"""
import base64
import html
import math
import random
from collections import Counter
from pathlib import Path

import cv2

from observatory.ascii_art import CHAR_ASPECT, image_to_ascii
from observatory.logio import (
    SIGHTING_MAX_DIST,
    SIGHTING_MAX_GAPS,
    group_sightings,
    parse_timestamp,
    spread_indices,
)

MAX_FIGURES = 12
NO_DETECTIONS = "No detections were recorded."
NO_NOTES = "No speculative notes were written."

# Only this project file. A missing file becomes CSS paper, not a substitute image.
TEXTURE_NAME = "paper texture .jpg"


def default_texture_path():
    return Path(__file__).resolve().parents[1] / "poetic surveillance" / TEXTURE_NAME


def find_texture(explicit=None):
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    path = default_texture_path()
    return path if path.is_file() else None


def format_rgb(red, green, blue):
    channels = []
    for value in (red, green, blue):
        number = int(value)
        if number < 0 or number > 255:
            raise ValueError(f"RGB channel out of range: {value}")
        channels.append(str(number))
    return f"rgb({channels[0]}, {channels[1]}, {channels[2]})"


def escape_text(value):
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def seed_from_session(meta):
    import hashlib
    classes = meta.get("classes") or []
    material = "|".join([
        str(meta.get("started", "")),
        str(meta.get("ended", "")),
        str(meta.get("interval_s", "")),
        str(meta.get("camera", "")),
        ",".join(str(name) for name in classes),
        "all" if meta.get("all_classes") else "filtered",
    ])
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16)


def _box_fraction(detection):
    box = detection.get("bbox")
    width = detection.get("frame_width") or 0
    height = detection.get("frame_height") or 0
    if not box or len(box) != 4 or width <= 0 or height <= 0:
        return 0.12
    box_w = max(0.0, float(box[2]) - float(box[0]))
    box_h = max(0.0, float(box[3]) - float(box[1]))
    return (box_w * box_h) / (width * height)


def column_count(detection, rng):
    fraction = _box_fraction(detection)
    base = 22 + int(min(1.0, fraction * 4) * 46)
    return max(18, min(76, base + rng.randint(-3, 5)))


def random_ink(rng):
    """Random rgb(r, g, b) with each channel in 0–255.

    A color that sits too close to the cream paper is drawn again so the ASCII
    stays visible. The value is still a full RGB triple, not a named palette.
    """
    red = green = blue = 0
    for _ in range(16):
        red, green, blue = rng.randrange(256), rng.randrange(256), rng.randrange(256)
        distance = ((red - 243) ** 2 + (green - 239) ** 2 + (blue - 230) ** 2) ** 0.5
        if distance >= 140:
            break
    return format_rgb(red, green, blue)


def plan_layout(detections, seed):
    """Scatter figures from the session seed.

    Index picks a loose cell so one seed cannot pile every crop on the same edge.
    The seed still chooses the jitter, scale, color, and rotation.
    """
    rng = random.Random(seed)
    count = len(detections)
    columns = 2 if count <= 3 else 3
    row_count = max(1, math.ceil(count / columns)) if count else 1
    plans = []
    for index, detection in enumerate(detections):
        column = index % columns
        row = index // columns
        left = column * (68 / columns) + rng.uniform(0, 10)
        top = row * (64 / row_count) + rng.uniform(0, 7)
        plans.append({
            "index": index,
            "left": round(min(70, max(0, left)), 2),
            "top": round(min(72, max(0, top)), 2),
            "font_px": rng.choice([8, 9, 11, 13, 16]),
            "color": random_ink(rng),
            "rotate": round(rng.uniform(-3, 3), 2),
            "z": rng.randint(1, 3),
            "cols": column_count(detection, rng),
            "chip_left": round(rng.uniform(2, 24), 2),
            "chip_top": round(rng.uniform(6, 28), 2),
            "note_left": round(rng.uniform(0, 18), 2),
            "note_top": round(rng.uniform(20, 46), 2),
        })
    return plans


def place_piece(plan, art, stage_w=820, stage_h=1040):
    """Shrink and shift a figure so it stays on the sheet instead of being clipped."""
    rows = max(1, art.count("\n") + 1)
    cols = max(1, int(plan["cols"]))
    font = int(plan["font_px"])
    while font > 7 and (rows * font > stage_h * 0.40 or cols * font * 0.62 > stage_w * 0.46):
        font -= 1
    piece_h = rows * font
    piece_w = cols * font * 0.62
    max_top = max(0.0, stage_h - piece_h - 36)
    max_left = max(0.0, stage_w - piece_w - 12)
    top = min(float(plan["top"]) / 100.0 * stage_h, max_top)
    left = min(float(plan["left"]) / 100.0 * stage_w, max_left)
    return font, round(left, 1), round(top, 1)


def _fmt_date(value):
    moment = parse_timestamp(value)
    if moment is None:
        return escape_text(value) if value else "date not recorded"
    return f"{moment.month:02d}/{moment.day:02d}/{moment.year}"


def _fmt_time(value):
    moment = parse_timestamp(value)
    if moment is None:
        return escape_text(value) if value else "time not recorded"
    hour = str(moment.hour % 12 or 12)
    return f"{hour}:{moment.strftime('%M %p')}"


def _fmt_conf(value):
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return escape_text(value)


def _position_phrase(position):
    if not isinstance(position, dict):
        return "position not recorded"
    vertical = position.get("vertical") or "?"
    horizontal = position.get("horizontal") or "?"
    cx = position.get("cx")
    cy = position.get("cy")
    words = f"{vertical} {horizontal}"
    if cx is None or cy is None:
        return words
    return f"{words} ({float(cx):.2f}, {float(cy):.2f})"


def detection_count_phrase(detections):
    counts = Counter((item.get("class_name") or "unknown") for item in detections)
    parts = []
    for name in sorted(counts):
        parts.append(f"{counts[name]} {name}")
    return ", ".join(parts)


def sighting_count_phrase(groups):
    counts = Counter(group["class_name"] for group in groups)
    parts = [f"{counts[name]} {name}" for name in sorted(counts)]
    return ", ".join(parts)


def _drawable(session_dir, detections):
    chosen = []
    for detection in detections:
        crop = detection.get("crop")
        if crop and (Path(session_dir) / crop).is_file():
            chosen.append(detection)
    indexes = spread_indices(len(chosen), MAX_FIGURES)
    return [chosen[index] for index in indexes]


def _ascii_for(session_dir, detection, cols):
    crop = detection.get("crop")
    if not crop:
        return ""
    path = Path(session_dir) / crop
    if not path.is_file():
        return ""
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return ""
    return image_to_ascii(image, cols=cols, char_aspect=CHAR_ASPECT)


def _notes_by_crop(speculations):
    grouped = {}
    for note in speculations or []:
        if not isinstance(note, dict):
            continue
        text = str(note.get("text") or "").strip()
        if not text:
            continue
        grouped.setdefault(note.get("crop"), []).append(note)
    return grouped


def _paper_css(texture_bytes):
    if texture_bytes:
        encoded = base64.b64encode(texture_bytes).decode("ascii")
        rules = (
            "background-color: #f3efe6;"
            "background-image: linear-gradient(rgba(255,250,242,0.38), rgba(255,250,242,0.38)), "
            f'url("data:image/jpeg;base64,{encoded}");'
            "background-size: auto, cover;"
            "background-position: center;"
        )
        return rules, "paper-texture"
    rules = (
        "background-color: #efe6d4;"
        "background-image: radial-gradient(rgba(70,50,30,0.055) 0.65px, transparent 0.75px), "
        "radial-gradient(rgba(255,255,255,0.4) 0.55px, transparent 0.75px);"
        "background-size: 3px 3px, 7px 7px;"
        "background-position: 0 0, 1px 2px;"
    )
    return rules, "paper-css"


def _stopped_sentence(stopped):
    sentences = {
        "duration": "The watch stopped because the requested duration ended.",
        "interrupt": "The watch stopped by Ctrl-C. This log is partial.",
        "quit": "The watch stopped from the window. This log is partial.",
        "gesture": "The watch stopped on Quiet Coyote. This log is partial.",
    }
    return sentences.get(stopped, "The log does not say how the watch stopped.")


def _notes_lead(status, speculations, detections):
    if speculations:
        lead = "These lines are imagination from local Qwen. They are not verified observations."
        if status == "partial":
            lead += " Some notes were not generated because Ollama stopped answering."
        if status in {"saved", "failed-kept-saved"}:
            lead += " They were loaded from this session and Ollama was not called again."
        return lead
    if not detections or status == "no-crops":
        return NO_NOTES
    if status == "skipped":
        return "Speculative notes were not requested."
    if status == "failed":
        return (
            "Speculative notes were not generated because Ollama did not answer. "
            "No imagined text was added."
        )
    return NO_NOTES


def render_poster(session_dir, meta, detections, samples, speculations, seed,
                  texture_bytes=None, note_status="skipped"):
    session_dir = Path(session_dir)
    meta = meta or {}
    detections = list(detections or [])
    samples = list(samples or [])
    speculations = [note for note in (speculations or []) if isinstance(note, dict) and str(note.get("text") or "").strip()]
    paper_rules, paper_kind = _paper_css(texture_bytes)
    drawn = _drawable(session_dir, detections)
    layout = plan_layout(drawn, seed)
    notes_for = _notes_by_crop(speculations)
    started = meta.get("started")
    ended = meta.get("ended")
    if samples:
        started = samples[0].get("timestamp") or started
        ended = samples[-1].get("timestamp") or ended

    pieces = []
    for detection, plan in zip(drawn, layout):
        art = _ascii_for(session_dir, detection, plan["cols"])
        if not art:
            continue
        chip = (
            f'<div class="chip" style="left:{plan["chip_left"]}%;top:{plan["chip_top"]}%">'
            f'<span class="time">{_fmt_time(detection.get("timestamp"))}</span>'
            f'{escape_text(detection.get("class_name"))}<br>'
            f'conf {_fmt_conf(detection.get("confidence"))}<br>'
            f'{escape_text(_position_phrase(detection.get("position")))}'
            f'</div>'
        )
        note_html = []
        for note in notes_for.get(detection.get("crop"), []):
            note_html.append(
                f'<div class="note" style="left:{plan["note_left"]}%;top:{plan["note_top"]}%">'
                f'<span class="label">Qwen imagines</span>'
                f'<span class="sub">speculative note, not a verified fact</span>'
                f'{escape_text(note.get("text"))}'
                f'</div>'
            )
        font_px, left_px, top_px = place_piece(plan, art)
        pieces.append(
            f'<div class="piece" style="left:{left_px}px;top:{top_px}px;z-index:{plan["z"]}">'
            f'<pre class="ascii" style="color:{plan["color"]};font-size:{font_px}px;'
            f'transform:rotate({plan["rotate"]}deg)">{escape_text(art)}</pre>'
            f'{chip}{"".join(note_html)}</div>'
        )

    if not detections:
        summary = NO_DETECTIONS
        if samples:
            summary += (
                f" The camera took {len(samples)} samples from {_fmt_time(started)} to {_fmt_time(ended)} "
                "and logged none."
            )
        else:
            summary += " The log has no samples and no detections."
        sighting = ""
    else:
        noun = "detection" if len(detections) == 1 else "detections"
        summary = f"{len(detections)} {noun} ({detection_count_phrase(detections)})."
        groups = group_sightings(detections, meta.get("interval_s"))
        sighting = (
            f"Approximate sightings: {sighting_count_phrase(groups)}. "
            f"A sighting groups detections of the same class when their centers are within "
            f"{SIGHTING_MAX_DIST} of the frame and the gap is at most {SIGHTING_MAX_GAPS} sample intervals. "
            "That is nearby repeats, not a claim that the detector recognized the same individual."
        )
    if drawn and len(drawn) < len([item for item in detections if item.get("crop")]):
        summary += (
            f" The sheet draws {len(pieces)} of the saved crops, spaced through the watch. "
            "Every detection is in the table."
        )

    watched = "all COCO classes" if meta.get("all_classes") else ", ".join(meta.get("classes") or []) or "not recorded"
    failed_frames = sum(1 for sample in samples if sample.get("frame_ok") is False)
    sample_line = f"{len(samples)} samples"
    if failed_frames:
        sample_line += f", {failed_frames} without a frame"
    period = f"{_fmt_time(started)} – {_fmt_time(ended)}" if ended else f"{_fmt_time(started)} – end time not written"

    rows = []
    if not detections:
        rows.append("<tr><td colspan=\"6\">None.</td></tr>")
    for detection in detections:
        box = detection.get("bbox") or []
        box_text = ", ".join(str(value) for value in box) if box else ""
        rows.append(
            "<tr>"
            f"<td>{_fmt_time(detection.get('timestamp'))}</td>"
            f"<td>{escape_text(detection.get('class_name'))}</td>"
            f"<td>{_fmt_conf(detection.get('confidence'))}</td>"
            f"<td>{escape_text(_position_phrase(detection.get('position')))}</td>"
            f"<td>{escape_text(box_text)}</td>"
            f"<td>{escape_text(detection.get('crop') or '')}</td>"
            "</tr>"
        )

    note_blocks = []
    for note in speculations:
        note_blocks.append(
            "<li>"
            f"<span class=\"label\">Qwen imagines</span> "
            f"{escape_text(note.get('class_name'))} {_fmt_time(note.get('timestamp'))}. "
            f"{escape_text(note.get('text'))}"
            "</li>"
        )
    notes_html = "<ul class=\"notes\">" + "".join(note_blocks) + "</ul>" if note_blocks else f"<p>{escape_text(_notes_lead(note_status, [], detections))}</p>"
    # The lead-in when notes exist is separate from the empty sentence.
    if note_blocks:
        notes_intro = f"<p>{escape_text(_notes_lead(note_status, speculations, detections))}</p>"
    else:
        notes_intro = ""

    stage_class = "stage" if pieces else "stage empty"
    if pieces:
        stage_body = "".join(pieces)
    else:
        stage_body = f'<p class="empty-line">{escape_text(NO_DETECTIONS if not detections else "No crop files were available to draw.")}</p>'

    conf = meta.get("conf")
    try:
        conf_text = f"{float(conf):.2f}"
    except (TypeError, ValueError):
        conf_text = "not recorded"
    interval = meta.get("interval_s")
    try:
        interval_text = f"{float(interval):g}"
    except (TypeError, ValueError):
        interval_text = "not recorded"

    title = f"Night Window {_fmt_date(meta.get('started') or started)}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape_text(title)}</title>
<style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  background: #d9d3c8;
  color: #1b140f;
  font-family: "Courier New", Courier, monospace;
}}
.sheet {{
  {paper_rules}
  width: min(920px, 100%);
  min-height: 1180px;
  margin: 0 auto;
  padding: 46px 50px 64px;
}}
.kicker {{
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}}
.date, .period {{
  margin: 2px 0 14px;
  font-size: 20px;
}}
.legend {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  font-size: 12px;
  max-width: 78ch;
  line-height: 1.4;
}}
.stage {{
  position: relative;
  height: 1040px;
  margin-top: 8px;
  overflow: visible;
}}
.stage.empty {{
  height: auto;
  min-height: 140px;
}}
.empty-line {{ margin: 48px 0; font-size: 16px; }}
.piece {{ position: absolute; }}
.ascii {{
  margin: 0;
  line-height: 1;
  letter-spacing: 0;
  font-family: "Courier New", Courier, monospace;
  white-space: pre;
  transform-origin: top left;
  text-shadow: 0 0 1px rgba(30, 20, 10, 0.45);
}}
.chip, .note {{
  position: absolute;
  color: #1b140f;
  background: rgba(255, 249, 240, 0.93);
  padding: 6px 8px;
}}
.chip {{
  z-index: 2;
  max-width: 24ch;
  font-size: 12px;
  line-height: 1.35;
}}
.chip .time {{ display: block; }}
.note {{
  z-index: 3;
  max-width: 28ch;
  font-family: Palatino, "Palatino Linotype", Georgia, serif;
  font-style: italic;
  font-size: 14px;
  line-height: 1.35;
}}
.note .label, .notes .label {{
  display: block;
  font-family: "Courier New", Courier, monospace;
  font-style: normal;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 3px;
}}
.note .sub {{
  display: block;
  font-family: "Courier New", Courier, monospace;
  font-style: normal;
  font-size: 9px;
  letter-spacing: 0.03em;
  margin-bottom: 4px;
}}
.record {{
  position: relative;
  z-index: 5;
  margin-top: 28px;
  padding-top: 8px;
  background: rgba(255, 250, 242, 0.96);
  color: #1b140f;
}}
.record h2 {{
  margin: 18px 0 8px;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  border-top: 1px solid rgba(40, 30, 20, 0.28);
  padding-top: 14px;
}}
.record p, .notes {{
  margin: 0 0 10px;
  font-size: 13px;
  max-width: 78ch;
  line-height: 1.45;
}}
.notes {{ padding-left: 18px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th, td {{
  text-align: left;
  vertical-align: top;
  padding: 4px 10px 4px 0;
  border-bottom: 1px solid rgba(40, 30, 20, 0.12);
  word-break: break-word;
}}
@media print {{
  body {{ background: white; }}
  .sheet {{ width: auto; min-height: 0; }}
}}
</style>
</head>
<body>
<article class="sheet {paper_kind}" data-paper="{paper_kind}">
  <header>
    <p class="kicker">date</p>
    <p class="date">{_fmt_date(meta.get("started") or started)}</p>
    <p class="kicker">observation period</p>
    <p class="period">{period}</p>
    <ul class="legend">
      <li><b>Observation.</b> Detector class, time, confidence, and position. This is the log.</li>
      <li><b>Artwork.</b> ASCII made from the saved crop, locally. Qwen does not draw it.</li>
      <li><b>Qwen imagines.</b> A speculative note. Not a verified fact.</li>
    </ul>
  </header>
  <section class="{stage_class}">
    {stage_body}
  </section>
  <section class="record">
    <h2>Observations</h2>
    <p>{escape_text(summary)}</p>
    <p>{escape_text(sighting)}</p>
    <p>{escape_text(sample_line + ". " + _stopped_sentence(meta.get("stopped")))} Session {escape_text(meta.get("id") or "")}. Camera {escape_text(meta.get("camera"))}. Model {escape_text(meta.get("model"))}. Confidence threshold {escape_text(conf_text)}. Interval {escape_text(interval_text)} s. Classes: {escape_text(watched)}.</p>
    <table>
      <thead>
        <tr><th>time</th><th>class</th><th>confidence</th><th>position</th><th>box</th><th>crop</th></tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
    <h2>Speculative notes</h2>
    {notes_intro}
    {notes_html}
    <h2>Limits</h2>
    <p class="limits">YOLO may miss an object, mislabel it, or mark something that is not there. The class and confidence in the table are the detector's record, not a checked fact. Qwen's notes are imagination and can invent visual details. A box is not a silhouette: the crop keeps the background inside the rectangle, and the ASCII keeps it too.</p>
  </section>
</article>
</body>
</html>
"""


def write_poster(session_dir, meta, detections, samples, speculations, seed,
                 texture_bytes=None, note_status="skipped"):
    html_text = render_poster(
        session_dir, meta, detections, samples, speculations, seed,
        texture_bytes=texture_bytes, note_status=note_status,
    )
    path = Path(session_dir) / "poster.html"
    path.write_text(html_text, encoding="utf-8")
    return path
