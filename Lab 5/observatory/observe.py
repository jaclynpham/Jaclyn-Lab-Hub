"""Watch the window one frame at a time, then write one postcard.

The camera and YOLO call follow yolo_person.py and overnight.py: VideoCapture at
640x480, YOLO predict with imgsz, conf, and a class filter. `--all` passes
classes=None. Full frames are not saved. Crops live in a temporary folder until
the postcard is written, then that folder is removed. Ctrl-C closes the camera
and still writes the postcard from whatever was seen.
"""
import datetime
import re
import tempfile
import time
from pathlib import Path

import cv2

from observatory.coco import class_names_from_args, resolve_class_ids
from observatory.gesture import is_quiet_coyote, landmarks_from, try_hand_detector
from observatory.logio import make_detection
from observatory.postcard import (
    layered_drawings,
    load_texture_bytes,
    retain_only,
    select_sightings,
    write_record_log,
    write_postcard,
)
from observatory.poster import seed_from_session
from observatory.qwen_notes import DEFAULT_MODEL, collect_notes
from observatory.segment import crop_window, open_segmenter

PAD_FRAC = 0.10
PRIVACY_WARNING = (
    "Privacy: get consent from everyone in the household, and point the camera away from "
    "beds and from neighboring windows. Crops are kept only while the postcard is drawn, "
    "then removed. The session folder keeps morning_postcard.png."
)


class ObservationStopped(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def open_camera(index):
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        cap.release()
        raise SystemExit(f"no webcam found at index {index}: is it plugged in?")
    return OpenCVCamera(cap)


class OpenCVCamera:
    """Skip the buffered frames, as overnight.py does, then read one."""

    def __init__(self, cap):
        self.cap = cap

    def read(self):
        for _ in range(3):
            self.cap.grab()
        return self.cap.read()

    def release(self):
        self.cap.release()


def build_predictor(model_path, conf, imgsz, class_names):
    if not Path(model_path).exists():
        raise SystemExit(
            f"YOLO model not found at {model_path}. From Lab 5, export it once:\n"
            "  python -c \"from ultralytics import YOLO; YOLO('yolo26n.pt').export(format='ncnn')\""
        )
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit(
            "ultralytics is not installed, so YOLO cannot run. "
            "Use the Lab 5 virtualenv and pip install -r requirements.txt. "
            f"({exc})"
        ) from exc
    model = YOLO(str(model_path))
    class_ids = None if class_names is None else resolve_class_ids(model.names, class_names)

    def predict(frame):
        result = model.predict(
            frame, imgsz=imgsz, conf=conf, classes=class_ids,
            show=False, save=False, verbose=False,
        )[0]
        return boxes_from_result(result, model.names)

    return predict


def boxes_from_result(result, names):
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []
    found = []
    for box, cls, conf in zip(boxes.xyxy, boxes.cls, boxes.conf):
        x1, y1, x2, y2 = box.tolist()
        class_id = int(cls)
        found.append({
            "class_id": class_id,
            "class_name": str(names[class_id]),
            "confidence": float(conf),
            "xyxy": [x1, y1, x2, y2],
        })
    return found


def padded_crop(frame, xyxy, pad_frac=PAD_FRAC):
    crop, _bounds = crop_window(frame, xyxy, pad_frac)
    return crop


def create_session_dir(parent):
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    session_dir = parent / stamp
    suffix = 2
    while session_dir.exists():
        session_dir = parent / f"{stamp}-{suffix}"
        suffix += 1
    session_dir.mkdir()
    return session_dir


def make_sleeper(show):
    if not show:
        return time.sleep

    def sleeper(seconds):
        deadline = time.time() + max(0.0, seconds)
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            key = cv2.waitKey(max(1, min(200, int(remaining * 1000))))
            if key != -1 and (key & 0xFF) == ord("q"):
                raise ObservationStopped("quit")

    return sleeper


def _plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _save_isolated(crop, mask, work_dir, timestamp, class_name, sample_index, det_index):
    safe = re.sub(r"[^a-z0-9]+", "-", class_name.lower()).strip("-") or "object"
    try:
        stamp = datetime.datetime.fromisoformat(timestamp).strftime("%Y%m%d-%H%M%S")
    except ValueError:
        stamp = "time"
    stem = f"{stamp}-s{sample_index}-{safe}-{det_index}"
    crop_path = Path(work_dir) / f"{stem}.png"
    mask_path = Path(work_dir) / f"{stem}-mask.png"
    shown = crop.copy()
    shown[mask < 128] = 255
    if not cv2.imwrite(str(crop_path), shown) or not cv2.imwrite(str(mask_path), mask):
        print(f"could not save {crop_path}", flush=True)
        return None, None
    return str(crop_path), str(mask_path)


def _show_frame(frame, records, seconds_left):
    view = frame.copy()
    for record in records:
        x1, y1, x2, y2 = [int(value) for value in record["bbox"]]
        cv2.rectangle(view, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{record['class_name']} {record['confidence']:.2f}"
        cv2.putText(view, label, (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.putText(
        view, f"{max(0, int(seconds_left))} s left, q to stop",
        (10, view.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
    )
    cv2.imshow("Night Window", view)


def _sample_once(camera, predictor, segmenter, work_dir, detections, samples, counts, meta, show,
                 end, clock, detector, gesture_after, sensor_reader=None):
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    environment = None
    if sensor_reader is not None:
        try:
            environment = sensor_reader()
        except Exception as exc:
            print("sensor hiccup:", exc, flush=True)

    def sample_record(**values):
        record = {"timestamp": timestamp, **values}
        if environment is not None:
            record["temperature_c"], record["humidity_percent"] = environment
        return record

    try:
        ok, frame = camera.read()
    except ObservationStopped:
        raise
    except Exception as exc:
        print("hiccup:", exc, flush=True)
        samples.append(sample_record(detections=0, frame_ok=False))
        counts["samples"] += 1
        return
    if not ok or frame is None:
        print("could not read from the camera", flush=True)
        samples.append(sample_record(detections=0, frame_ok=False))
        counts["samples"] += 1
        return
    meta["frame_width"], meta["frame_height"] = int(frame.shape[1]), int(frame.shape[0])
    if detector is not None and clock() >= gesture_after:
        try:
            if is_quiet_coyote(landmarks_from(detector, frame)):
                raise ObservationStopped("gesture")
        except ObservationStopped:
            raise
        except Exception as exc:
            print("gesture hiccup:", exc, flush=True)
    try:
        found = predictor(frame) or []
    except ObservationStopped:
        raise
    except Exception as exc:
        print("hiccup:", exc, flush=True)
        samples.append(sample_record(detections=0, frame_ok=True))
        counts["samples"] += 1
        return
    segmenter.begin_frame(frame)
    records = []
    for index, item in enumerate(found):
        crop, mask = segmenter.isolate(frame, item["xyxy"], item["class_name"])
        record = make_detection(item, frame.shape, None, timestamp)
        if crop is not None and mask is not None:
            crop_path, mask_path = _save_isolated(
                crop, mask, work_dir, timestamp, item["class_name"], counts["samples"], index,
            )
            if crop_path and mask_path:
                record["crop_path"] = crop_path
                record["mask_path"] = mask_path
        records.append(record)
        detections.append(record)
    samples.append(sample_record(detections=len(records), frame_ok=True))
    counts["samples"] += 1
    counts["detections"] += len(records)
    clock_text = timestamp[11:19]
    if environment is None:
        sensor_text = "temperature/humidity unavailable"
    else:
        sensor_text = f"{environment[0]:g}°C, {environment[1]:g}% humidity"
    if records:
        bits = [
            f"{record['class_name']} {record['confidence']:.2f} "
            f"{record['position']['vertical']}/{record['position']['horizontal']}"
            for record in records
        ]
        print(
            f"{clock_text} {len(records)} detection(s): {', '.join(bits)} | {sensor_text}",
            flush=True,
        )
    else:
        print(f"{clock_text} nothing in frame | {sensor_text}", flush=True)
    if show:
        _show_frame(frame, records, end - clock())


def run_observe(args, camera=None, predictor=None, clock=None, sleeper=None, sensor_reader=None):
    if args.duration <= 0 or args.interval <= 0:
        raise SystemExit("Duration and interval must be greater than 0.")
    class_names = class_names_from_args(args)
    clock = clock or time.time
    show = bool(getattr(args, "show", False))
    if sleeper is None:
        sleeper = make_sleeper(show)
    # Load the model before opening the camera so a missing weight file
    # does not leave the webcam running.
    if predictor is None:
        predictor = build_predictor(args.model, args.conf, args.imgsz, class_names)
    segmenter = open_segmenter(getattr(args, "seg_model", None), class_names, args.conf, args.imgsz)
    if camera is None:
        camera = open_camera(args.camera)

    session_dir = create_session_dir(args.output)
    started = datetime.datetime.now().isoformat(timespec="seconds")
    meta = {
        "project": "night-window",
        "id": session_dir.name,
        "started": started,
        "ended": None,
        "stopped": None,
        "duration_s": args.duration,
        "interval_s": args.interval,
        "camera": args.camera,
        "model": args.model,
        "imgsz": args.imgsz,
        "conf": args.conf,
        "all_classes": class_names is None,
        "classes": [] if class_names is None else list(class_names),
        "frame_width": None,
        "frame_height": None,
        "samples": 0,
        "detections": 0,
    }
    detections = []
    samples = []
    counts = {"samples": 0, "detections": 0}
    reason = "duration"
    work = tempfile.TemporaryDirectory(prefix="night-window-")
    print(PRIVACY_WARNING, flush=True)
    if args.duration > 60:
        print(f"Long watch: {args.duration:g} s. You set --duration explicitly.", flush=True)
    else:
        print(
            f"Short test watch: {args.duration:g} s. Pass --duration for a longer observation.",
            flush=True,
        )
    if args.interval < 1:
        print(
            f"Interval is {args.interval:g} s. That is very fast and will warm the Pi.",
            flush=True,
        )
    if class_names is None:
        print("Detecting all COCO classes.", flush=True)
    else:
        print("Detecting: " + ", ".join(class_names), flush=True)
    print(f"session: {session_dir}", flush=True)
    released = False
    cleaned = False

    def close_camera():
        nonlocal released
        if released:
            return
        released = True
        try:
            camera.release()
        finally:
            # HighGUI is what pops a window and what bus-errors on the Pi.
            # Leave it alone unless this run actually opened one.
            if show:
                try:
                    cv2.destroyAllWindows()
                except Exception:
                    pass

    def cleanup_work():
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        work.cleanup()

    try:
        try:
            detector = None
            if getattr(args, "gesture", False):
                detector = try_hand_detector()
                if detector is not None:
                    _wait_for_coyote(camera, detector, args.gesture_wait, sleeper, clock, show)
            start = clock()
            end = start + args.duration
            next_sample = start
            gesture_after = start + 2
            while True:
                now = clock()
                if now >= end:
                    reason = "duration"
                    break
                if now < next_sample:
                    sleeper(min(next_sample - now, end - now))
                    continue
                _sample_once(
                    camera, predictor, segmenter, work.name, detections, samples, counts, meta,
                    show, end, clock, detector, gesture_after, sensor_reader,
                )
                next_sample = now + args.interval
        except KeyboardInterrupt:
            reason = "interrupt"
            print("\nCtrl-C, writing the postcard from this partial watch.", flush=True)
        except ObservationStopped as exc:
            reason = exc.reason
            print(f"Stopped ({reason}), writing the postcard from this partial watch.", flush=True)
        except Exception:
            reason = "error"
            close_camera()
            try:
                _publish_postcard(args, session_dir, meta, detections, samples, counts, reason)
            finally:
                cleanup_work()
            raise
        close_camera()
        _publish_postcard(args, session_dir, meta, detections, samples, counts, reason)
    finally:
        close_camera()
        cleanup_work()
    return session_dir


def _publish_postcard(args, session_dir, meta, detections, samples, counts, reason):
    meta["ended"] = datetime.datetime.now().isoformat(timespec="seconds")
    meta["stopped"] = reason
    meta["samples"] = counts["samples"]
    meta["detections"] = counts["detections"]
    print(f"stopped: {reason}", flush=True)
    print(
        f"{_plural(counts['samples'], 'sample')}, {_plural(counts['detections'], 'detection')}",
        flush=True,
    )
    if counts["detections"] == 0:
        print("No detections recorded.", flush=True)
    reps = select_sightings(detections, meta.get("interval_s"))
    drawn = layered_drawings(detections, meta.get("interval_s"))
    print(
        f"postcard figures: {len(drawn)} layered frames across {len(reps)} sightings, "
        f"from {counts['detections']} detections. Nearby repeats share one caption. "
        "That is not the same individual.",
        flush=True,
    )
    skip = bool(getattr(args, "skip_qwen", False))
    cap = int(getattr(args, "qwen_cap", 3))
    model = getattr(args, "qwen_model", None) or DEFAULT_MODEL
    notes, status = collect_notes(reps, skip=skip, cap=cap, model=model)
    seed = getattr(args, "seed", None)
    if seed is None:
        seed = seed_from_session(meta)
    texture_bytes, _looked = load_texture_bytes(getattr(args, "texture", None))
    path = write_postcard(
        session_dir / "morning_postcard.png",
        meta, detections, samples, notes, seed,
        texture_bytes=texture_bytes, note_status=status,
    )
    record_path = write_record_log(
        session_dir / "morning_postcard_records.txt",
        meta, detections, samples, notes,
    )
    retain_only(session_dir, [path, record_path])
    print(f"postcard: {path}", flush=True)
    print(f"record log: {record_path}", flush=True)
    print(f"speculative notes: {status}", flush=True)


def _wait_for_coyote(camera, detector, timeout_s, sleeper, clock, show):
    print("Hold Quiet Coyote to start, or wait and the timer starts anyway.", flush=True)
    deadline = clock() + timeout_s
    while clock() < deadline:
        ok, frame = camera.read()
        if ok and frame is not None:
            try:
                if is_quiet_coyote(landmarks_from(detector, frame)):
                    print("Quiet Coyote: watch started.", flush=True)
                    return
            except Exception as exc:
                print("gesture hiccup:", exc, flush=True)
            if show:
                cv2.imshow("Night Window", frame)
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(0.3, remaining))
    print("No gesture. Starting on the timer.", flush=True)
