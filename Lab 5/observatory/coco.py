"""COCO class names for the window watch.

YOLO26n uses the 80 COCO classes, same as yolo_person.py. Class 0 is person.
`--all` leaves the filter empty so YOLO returns every class, matching that script.
"""

COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake",
    "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop",
    "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]

# A window can plausibly see these. Pass --all for the other 75.
WINDOW_CLASSES = ["person", "bird", "bus", "car", "dog"]

COCO_NAME_SET = set(COCO_CLASSES)


def parse_class_names(text):
    """Turn 'bird, car' into COCO names. Raises SystemExit on an unknown name."""
    names = [part.strip().lower() for part in str(text).split(",") if part.strip()]
    if not names:
        raise SystemExit("No classes given. Pass --classes bird,car or --all.")
    unknown = [name for name in names if name not in COCO_NAME_SET]
    if unknown:
        raise SystemExit(
            "Unknown COCO class: " + ", ".join(unknown) + ". "
            "Use names like person, bird, bus, car, dog, or pass --all."
        )
    return names


def class_names_from_args(args):
    """None means all classes, the same convention as --all in yolo_person.py."""
    if args.all:
        return None
    return parse_class_names(args.classes)


def resolve_class_ids(names, wanted):
    """Map class names to the ids this YOLO model actually uses."""
    by_name = {str(label): int(key) for key, label in names.items()}
    missing = [name for name in wanted if name not in by_name]
    if missing:
        raise SystemExit("This model has no class named: " + ", ".join(missing))
    return [by_name[name] for name in wanted]
