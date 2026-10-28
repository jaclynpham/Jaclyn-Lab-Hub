"""Portrait postcard for one watch. The only file the session keeps.

ASCII comes from the crop pixels. Qwen, when it answers, supplies a labeled
speculative note and does not draw the picture. Layout and colors come from
the session seed, so the same session renders the same card.
"""
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from observatory.ascii_art import CHAR_ASPECT, image_to_ascii
from observatory.logio import group_sightings, parse_timestamp, spread_indices
from observatory.poster import (
    MAX_FIGURES,
    SIGHTING_MAX_DIST,
    SIGHTING_MAX_GAPS,
    detection_count_phrase,
    find_texture,
    plan_layout,
    place_piece,
    sighting_count_phrase,
)

POSTCARD_WIDTH = 1470
POSTCARD_HEIGHT = 2108
NO_DETECTIONS = "No detections recorded."
INK = (28, 22, 16)
CREAM = (255, 249, 240)

MONO_FONTS = (
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
)
SERIF_FONTS = (
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
)


def _font(size, serif=False):
    for path in SERIF_FONTS if serif else MONO_FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default(size=size)


def _fmt_date(value):
    moment = parse_timestamp(value)
    if moment is None:
        return str(value) if value else "date not recorded"
    return f"{moment.month:02d}/{moment.day:02d}/{moment.year}"


def _fmt_time(value):
    moment = parse_timestamp(value)
    if moment is None:
        return str(value) if value else "time not recorded"
    hour = str(moment.hour % 12 or 12)
    return f"{hour}:{moment.strftime('%M %p')}"


def _fmt_conf(value):
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


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


def _span(meta, samples):
    started = (meta or {}).get("started")
    ended = (meta or {}).get("ended") or started
    if samples:
        started = samples[0].get("timestamp") or started
        ended = samples[-1].get("timestamp") or ended
    return started, ended


def postcard_content(meta, detections, samples, speculations, note_status="skipped"):
    """The words drawn on the card. Facts and speculative notes stay in separate fields."""
    meta = meta or {}
    detections = list(detections or [])
    samples = list(samples or [])
    speculations = [
        note for note in (speculations or [])
        if isinstance(note, dict) and str(note.get("text") or "").strip()
    ]
    started, ended = _span(meta, samples)
    date = _fmt_date(meta.get("started") or started)
    if ended:
        period = f"{_fmt_time(started)} – {_fmt_time(ended)}"
    else:
        period = f"{_fmt_time(started)} – end time not written"
    if not detections:
        summary = NO_DETECTIONS
        if samples:
            summary += (
                f" {len(samples)} samples from {_fmt_time(started)} to {_fmt_time(ended)} logged none."
            )
        else:
            summary += " The log has no samples and no detections."
        sighting = ""
        rows = []
    else:
        noun = "detection" if len(detections) == 1 else "detections"
        summary = f"{len(detections)} {noun} ({detection_count_phrase(detections)})."
        groups = group_sightings(detections, meta.get("interval_s"))
        sighting = (
            f"Approximate sightings: {sighting_count_phrase(groups)}. "
            f"A sighting groups the same class when centers stay within {SIGHTING_MAX_DIST} "
            f"of the frame and the gap is at most {SIGHTING_MAX_GAPS} sample intervals. "
            "That is nearby repeats, not the same individual."
        )
        rows = [
            f"{_fmt_time(item.get('timestamp'))}  {item.get('class_name')}  "
            f"conf {_fmt_conf(item.get('confidence'))}  {_position_phrase(item.get('position'))}"
            for item in detections
        ]
    if speculations:
        notes = [
            "These lines are imagination from local Qwen. They are not verified observations."
        ]
        for note in speculations:
            notes.append(
                f"Qwen imagines · speculative note · {_fmt_time(note.get('timestamp'))} "
                f"{note.get('class_name')}: {str(note.get('text')).strip()}"
            )
    elif note_status == "skipped" and detections:
        notes = ["Speculative notes were not requested."]
    elif note_status == "failed":
        notes = ["Speculative notes were not generated because Ollama did not answer."]
    else:
        notes = ["No speculative notes were written."]
    limits = (
        "YOLO boxes are not silhouettes, so the ASCII keeps some surrounding scene. "
        "Class, time, and confidence are the detector record, not a checked fact. "
        "Qwen imagines is a speculative note."
    )
    return {
        "date": date,
        "period": period,
        "summary": summary,
        "sighting": sighting,
        "rows": rows,
        "notes": notes,
        "limits": limits,
    }


def _cover_texture(texture_bytes, width, height):
    texture = Image.open(io.BytesIO(texture_bytes)).convert("RGB")
    scale = max(width / texture.width, height / texture.height)
    resized = texture.resize(
        (max(width, int(texture.width * scale) + 1), max(height, int(texture.height * scale) + 1)),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def paper_background(width, height, seed, texture_bytes=None):
    """Subtle paper. The supplied texture is washed back; otherwise a seeded fiber field."""
    if texture_bytes:
        cover = _cover_texture(texture_bytes, width, height)
        wash = Image.new("RGB", (width, height), (250, 246, 236))
        return Image.blend(cover, wash, 0.40)
    rng = np.random.default_rng(int(seed) % (2**32))
    field = rng.integers(234, 247, (height, width), dtype=np.uint8)
    count = 2400
    ys = rng.integers(0, height, count)
    xs = rng.integers(0, width, count)
    field[ys, xs] = rng.integers(176, 214, count).astype(np.uint8)
    return Image.fromarray(field, mode="L").convert("RGB")


def _parse_rgb(text):
    parts = [int(piece) for piece in str(text).replace("rgb", "").replace("(", "").replace(")", "").split(",") if piece.strip()]
    if len(parts) != 3:
        return INK
    return tuple(max(0, min(255, value)) for value in parts)


def _wrap(draw, text, font, width):
    text = " ".join(str(text).split())
    if not text:
        return []
    lines = []
    current = ""
    for word in text.split(" "):
        trial = word if not current else current + " " + word
        if draw.textlength(trial, font=font) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        if draw.textlength(word, font=font) <= width:
            current = word
            continue
        chunk = ""
        for character in word:
            if draw.textlength(chunk + character, font=font) <= width:
                chunk += character
            else:
                if chunk:
                    lines.append(chunk)
                chunk = character
        current = chunk
    if current:
        lines.append(current)
    return lines


def _rows_that_fit(wrapped_rows, room, line_h):
    """Keep every row when they fit. Otherwise keep an even spread across the watch."""
    if room <= line_h or not wrapped_rows:
        return []

    def height(rows):
        return sum(max(1, len(lines)) * line_h for lines in rows)

    if height(wrapped_rows) <= room:
        return wrapped_rows
    for cap in range(len(wrapped_rows) - 1, 0, -1):
        picked = [wrapped_rows[index] for index in spread_indices(len(wrapped_rows), cap)]
        if height(picked) <= room:
            return picked
    return []


def _crop_array(detection):
    image = detection.get("crop_image")
    if image is not None:
        return image
    path = detection.get("crop_path") or detection.get("crop")
    if path and Path(path).is_file():
        return cv2.imread(str(path), cv2.IMREAD_COLOR)
    return None


def _ascii_block(detection, cols):
    image = _crop_array(detection)
    if image is None:
        return ""
    return image_to_ascii(image, cols=cols, char_aspect=CHAR_ASPECT)


def render_postcard_image(meta, detections, samples, speculations, seed,
                          texture_bytes=None, note_status="skipped"):
    content = postcard_content(meta, detections, samples, speculations, note_status)
    width, height = POSTCARD_WIDTH, POSTCARD_HEIGHT
    image = paper_background(width, height, seed, texture_bytes)
    draw = ImageDraw.Draw(image)
    label = _font(22)
    date_font = _font(54)
    period_font = _font(46)
    legend_font = _font(20)
    margin = 78
    y = 72
    draw.text((margin, y), "DATE", font=label, fill=INK)
    y += 30
    draw.text((margin, y), content["date"], font=date_font, fill=INK)
    y += 68
    draw.text((margin, y), "OBSERVATION PERIOD", font=label, fill=INK)
    y += 32
    draw.text((margin, y), content["period"], font=period_font, fill=INK)
    y += 64
    legend = (
        "Observation: class, time, confidence, position.   "
        "Artwork: ASCII from the crop.   "
        "Qwen imagines: speculative note, not a verified fact."
    )
    for line in _wrap(draw, legend, legend_font, width - 2 * margin):
        draw.text((margin, y), line, font=legend_font, fill=INK)
        y += 26
    art_top = y + 18
    panel_top = 1588
    art_box = (margin, art_top, width - margin, panel_top - 16)
    art_w = art_box[2] - art_box[0]
    art_h = art_box[3] - art_box[1]
    art = Image.new("RGBA", (max(art_w, 1), max(art_h, 1)), (0, 0, 0, 0))
    art_draw = ImageDraw.Draw(art)
    drawn = [detection for detection in detections if _crop_array(detection) is not None]
    chosen = [drawn[index] for index in spread_indices(len(drawn), MAX_FIGURES)]
    layout = plan_layout(chosen, seed)
    by_key = {}
    for note in speculations or []:
        if isinstance(note, dict) and str(note.get("text") or "").strip():
            by_key.setdefault((note.get("timestamp"), note.get("class_name")), []).append(note)
    pieces = []
    for detection, plan in zip(chosen, layout):
        scaled = dict(plan)
        scaled["font_px"] = max(14, int(plan["font_px"] * 2.1))
        art_text = _ascii_block(detection, scaled["cols"])
        if not art_text:
            continue
        font_px, left, top = place_piece(scaled, art_text, stage_w=art_w, stage_h=art_h)
        font = _font(font_px)
        color = _parse_rgb(plan["color"])
        pieces.append({
            "detection": detection,
            "plan": plan,
            "art": art_text,
            "font": font,
            "font_px": font_px,
            "left": left,
            "top": top,
            "color": color,
            "notes": by_key.get((detection.get("timestamp"), detection.get("class_name")), []),
        })
    for piece in sorted(pieces, key=lambda item: item["plan"]["z"]):
        lines = piece["art"].splitlines()
        advance = piece["font"].getlength("0") or piece["font_px"] * CHAR_ASPECT
        step = max(1, int(round(advance / CHAR_ASPECT)))
        piece["step"] = step
        width_px = max((piece["font"].getlength(line) for line in lines), default=advance)
        block = Image.new("RGBA", (max(2, int(width_px) + 2), max(2, len(lines) * step + 2)), (0, 0, 0, 0))
        block_draw = ImageDraw.Draw(block)
        for index, line in enumerate(lines):
            block_draw.text((0, index * step), line, font=piece["font"], fill=piece["color"] + (255,))
        angle = piece["plan"]["rotate"]
        if abs(angle) > 0.2:
            block = block.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        art.paste(block, (int(piece["left"]), int(piece["top"])), block)
    chip_font = _font(22)
    note_font = _font(22, serif=True)
    note_label = _font(16)
    labels = []
    for piece in pieces:
        lines = piece["art"].splitlines() or [""]
        step = piece.get("step") or max(1, int(piece["font_px"]))
        block_w = max((art_draw.textlength(line, font=piece["font"]) for line in lines), default=40)
        block_h = max(step, len(lines) * step)
        chip_x = int(piece["left"] + block_w * piece["plan"]["chip_left"] / 100)
        chip_y = int(piece["top"] + block_h * min(piece["plan"]["chip_top"], 18) / 100)
        chip_lines = []
        for line in (
            _fmt_time(piece["detection"].get("timestamp")),
            str(piece["detection"].get("class_name")),
            f"conf {_fmt_conf(piece['detection'].get('confidence'))}",
            _position_phrase(piece["detection"].get("position")),
        ):
            chip_lines.extend(_wrap(art_draw, line, chip_font, 248))
        chip_w, chip_h = _box_size(chip_lines, chip_font, 264)
        chip_x, chip_y = _clamp_origin(chip_x, chip_y, chip_w, chip_h, art_w, art_h)
        labels.append({
            "lines": chip_lines,
            "x": chip_x,
            "y": chip_y,
            "w": chip_w,
            "h": chip_h,
            "notes": piece["notes"],
        })
    obstacles = [(item["x"], item["y"], item["x"] + item["w"], item["y"] + item["h"]) for item in labels]
    for item in labels:
        item["note_box"] = None
        if not item["notes"]:
            continue
        body = _wrap(art_draw, str(item["notes"][0].get("text")).strip(), note_font, 280)
        note_lines = ["Qwen imagines", "speculative note"] + body
        note_w, note_h = _box_size(note_lines, note_font, 296, label_font=note_label, label_lines=2)
        note_x, note_y = _note_beside_chip(
            item["x"], item["y"], item["w"], item["h"], note_w, note_h, art_w, art_h, obstacles,
        )
        item["note_box"] = (note_lines, note_x, note_y)
        obstacles.append((note_x, note_y, note_x + note_w, note_y + note_h))
    for item in labels:
        if item["note_box"] is None:
            continue
        note_lines, note_x, note_y = item["note_box"]
        _draw_backed_text(
            art_draw, note_lines, note_font, note_x, note_y, art_w, art_h,
            max_width=296, label_font=note_label, label_lines=2,
        )
    for item in labels:
        _draw_backed_text(art_draw, item["lines"], chip_font, item["x"], item["y"], art_w, art_h, max_width=264)
    if not pieces and not detections:
        empty_font = _font(42)
        art_draw.text((36, max(24, art_h // 3)), NO_DETECTIONS, font=empty_font, fill=INK + (255,))
    elif not pieces and detections:
        art_draw.text((36, 36), "No crop was available to draw.", font=_font(28), fill=INK + (255,))
    image.paste(art, (art_box[0], art_box[1]), art)

    panel = Image.new("RGBA", (width - 2 * margin, height - panel_top - 48), (255, 250, 242, 236))
    panel_draw = ImageDraw.Draw(panel)
    body = _font(22)
    small = _font(18)
    cursor = 16
    panel_draw.text((16, cursor), "OBSERVATIONS", font=label, fill=INK)
    cursor += 36
    for paragraph, font in (
        (content["summary"], body),
        (content["sighting"], small),
    ):
        if not paragraph:
            continue
        for line in _wrap(panel_draw, paragraph, font, panel.width - 32):
            if cursor > panel.height - 80:
                break
            panel_draw.text((16, cursor), line, font=font, fill=INK)
            cursor += int(getattr(font, "size", 18) * 1.25)
        cursor += 8
    row_font = _font(18)
    wrapped_rows = [_wrap(panel_draw, row, row_font, panel.width - 32) for row in content["rows"]]
    room = panel.height - 168 - cursor
    chosen_rows = _rows_that_fit(wrapped_rows, room, 22)
    for wrapped in chosen_rows:
        for line in wrapped:
            panel_draw.text((16, cursor), line, font=row_font, fill=INK)
            cursor += 22
    if len(chosen_rows) < len(content["rows"]):
        rest = (
            f"Showing {len(chosen_rows)} of {len(content['rows'])} detections, "
            "spaced across the watch. The postcard does not add detections."
        )
        for line in _wrap(panel_draw, rest, small, panel.width - 32):
            panel_draw.text((16, cursor), line, font=small, fill=INK)
            cursor += 22
    cursor += 8
    panel_draw.text((16, cursor), "SPECULATIVE NOTES", font=label, fill=INK)
    cursor += 34
    for paragraph in content["notes"]:
        for line in _wrap(panel_draw, paragraph, small, panel.width - 32):
            if cursor > panel.height - 70:
                break
            panel_draw.text((16, cursor), line, font=small, fill=INK)
            cursor += 22
        cursor += 4
    for line in _wrap(panel_draw, content["limits"], _font(16), panel.width - 32):
        if cursor > panel.height - 22:
            break
        panel_draw.text((16, cursor), line, font=_font(16), fill=INK)
        cursor += 20
    image.paste(panel, (margin, panel_top), panel)
    return image.convert("RGB")


def _line_height(font):
    return int(getattr(font, "size", 18) * 1.25)


def _box_size(lines, font, max_width, label_font=None, label_lines=0):
    widths = []
    height = 0
    for index, line in enumerate(lines):
        use = label_font if label_font is not None and index < label_lines else font
        widths.append(use.getlength(line))
        height += _line_height(use)
    box_w = min(max_width, (max(widths) if widths else 40)) + 16
    return box_w, 10 + height


def _clamp_origin(x, y, box_w, box_h, limit_w, limit_h):
    x = max(8, min(int(x), max(8, int(limit_w - box_w - 8))))
    y = max(8, min(int(y), max(8, int(limit_h - box_h - 8))))
    return x, y


def _overlaps(a, b, pad=8):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def _note_beside_chip(chip_x, chip_y, chip_w, chip_h, note_w, note_h, limit_w, limit_h, obstacles):
    """Keep the speculative note off observation chips."""
    gap = 14
    candidates = (
        (chip_x, chip_y + chip_h + gap),
        (chip_x + chip_w + gap, chip_y + chip_h + gap),
        (chip_x - note_w - gap, chip_y + chip_h + gap),
        (chip_x + chip_w + gap, chip_y),
        (chip_x - note_w - gap, chip_y),
        (chip_x, chip_y - note_h - gap),
    )
    for x, y in candidates:
        if x < 8 or y < 8 or x + note_w > limit_w - 8 or y + note_h > limit_h - 8:
            continue
        rect = (x, y, x + note_w, y + note_h)
        if any(_overlaps(rect, obstacle) for obstacle in obstacles):
            continue
        return int(x), int(y)
    return _clamp_origin(chip_x, chip_y + chip_h + gap, note_w, note_h, limit_w, limit_h)


def _draw_backed_text(draw, lines, font, x, y, limit_w, limit_h, max_width, label_font=None, label_lines=0):
    prepared = []
    for index, line in enumerate(lines):
        use = label_font if label_font is not None and index < label_lines else font
        prepared.append((line, use))
    box_w, box_h = _box_size(lines, font, max_width, label_font=label_font, label_lines=label_lines)
    x, y = _clamp_origin(x, y, box_w, box_h, limit_w, limit_h)
    draw.rectangle((x, y, min(limit_w - 4, x + box_w), y + box_h), fill=CREAM + (238,))
    cursor = y + 6
    for line, use in prepared:
        draw.text((x + 8, cursor), line, font=use, fill=INK + (255,))
        cursor += _line_height(use)


def write_postcard(path, meta, detections, samples, speculations, seed,
                   texture_bytes=None, note_status="skipped"):
    image = render_postcard_image(
        meta, detections, samples, speculations, seed,
        texture_bytes=texture_bytes, note_status=note_status,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    image.save(temporary, format="PNG")
    temporary.replace(path)
    return path


def retain_only(folder, keep):
    """Drop every file in the session folder except the finished postcard."""
    folder = Path(folder)
    keep = Path(keep).resolve()
    for path in sorted(folder.rglob("*"), reverse=True):
        if path.resolve() == keep:
            continue
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def load_texture_bytes(explicit=None):
    found = find_texture(explicit)
    if found is None:
        looked = explicit or "poetic surveillance/paper texture .jpg"
        print(f"Paper texture unavailable ({looked}). Postcard uses a generated paper background.", flush=True)
        return None, looked
    print(f"Paper texture: {found}", flush=True)
    return found.read_bytes(), str(found)
