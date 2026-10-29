"""Isolate an object inside a YOLO box before it becomes ASCII.

The detection model only returns a rectangle. This module never treats that
rectangle as a mask. It looks for a YOLO26 nano segmentation model, and if
that model is missing or returns no mask, it tries OpenCV GrabCut. A mask
that still fills the crop is rejected.
"""
from pathlib import Path

import cv2
import numpy as np

PAD_FRAC = 0.10
SEG_CANDIDATES = ("yolo26n-seg_ncnn_model", "yolo26n-seg.pt")


def crop_window(frame, xyxy, pad_frac=PAD_FRAC):
    """Padded crop and its (top, left, bottom, right) on the frame."""
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [float(value) for value in xyxy]
    pad_x = (x2 - x1) * pad_frac
    pad_y = (y2 - y1) * pad_frac
    left = max(0, int(x1 - pad_x))
    top = max(0, int(y1 - pad_y))
    right = min(width, int(x2 + pad_x + 0.999))
    bottom = min(height, int(y2 + pad_y + 0.999))
    if right - left < 2 or bottom - top < 2:
        return None, None
    return frame[top:bottom, left:right].copy(), (top, left, bottom, right)


def resolve_seg_path(explicit=None):
    """A segmentation checkpoint only. Nothing is loaded unless you pass a path.

    The NCNN segmentation export is not opened automatically: on the Pi that
    library can kill the process with Bus error. The detection model is not
    a candidate either.
    """
    if not explicit:
        return None
    path = Path(explicit)
    return path if path.exists() else None


def mask_is_isolated(mask):
    """True when the foreground is an object, not the whole crop or the GrabCut rectangle."""
    if mask is None or getattr(mask, "size", 0) == 0:
        return False
    gray = mask if mask.ndim == 2 else cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    foreground = gray >= 128
    ratio = float(foreground.mean())
    if ratio < 0.05 or ratio > 0.80:
        return False
    height, width = foreground.shape
    margin_x = max(2, int(width * 0.08))
    margin_y = max(2, int(height * 0.08))
    if width - 2 * margin_x < 4 or height - 2 * margin_y < 4:
        return False
    rectangle = np.zeros_like(foreground)
    rectangle[margin_y:height - margin_y, margin_x:width - margin_x] = True
    if float((foreground == rectangle).mean()) > 0.92:
        return False
    return True


def grabcut_mask(image):
    """OpenCV foreground estimate. This is not a YOLO mask."""
    if image is None or image.ndim != 3 or image.shape[2] < 3:
        return None
    bgr = image[:, :, :3]
    height, width = bgr.shape[:2]
    if height < 16 or width < 16:
        return None
    margin_x = max(2, int(width * 0.08))
    margin_y = max(2, int(height * 0.08))
    rect = (margin_x, margin_y, width - 2 * margin_x, height - 2 * margin_y)
    if rect[2] < 4 or rect[3] < 4:
        return None
    scratch = np.zeros((height, width), np.uint8)
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(bgr, scratch, rect, background, foreground, 3, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    binary = np.where(
        (scratch == cv2.GC_FGD) | (scratch == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return binary


def _class_name(names, class_id):
    if isinstance(names, dict):
        return str(names.get(class_id, names.get(str(class_id), "unknown")))
    return str(names[class_id])


def _as_numpy(value):
    if hasattr(value, "cpu"):
        value = value.cpu().numpy()
    return np.asarray(value)


def instances_from_result(result):
    """Pixel polygons from a segmentation result. Boxes alone produce nothing."""
    masks = getattr(result, "masks", None)
    boxes = getattr(result, "boxes", None)
    polygons = None if masks is None else getattr(masks, "xy", None)
    if boxes is None or polygons is None:
        return []
    xyxy = _as_numpy(boxes.xyxy)
    classes = _as_numpy(boxes.cls)
    names = getattr(result, "names", {})
    found = []
    for index, polygon in enumerate(polygons):
        points = np.asarray(polygon, dtype=np.float32)
        if points.ndim != 2 or points.shape[0] < 3:
            continue
        class_id = int(classes[index])
        found.append({
            "class_name": _class_name(names, class_id),
            "xyxy": [float(value) for value in xyxy[index][:4]],
            "polygon": points,
        })
    return found


def _iou(a, b):
    x1 = max(float(a[0]), float(b[0]))
    y1 = max(float(a[1]), float(b[1]))
    x2 = min(float(a[2]), float(b[2]))
    y2 = min(float(a[3]), float(b[3]))
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, float(a[2]) - float(a[0])) * max(0.0, float(a[3]) - float(a[1]))
    area_b = max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def _rasterize(polygon, bounds, shape):
    top, left, bottom, right = bounds
    mask = np.zeros((bottom - top, right - left), np.uint8)
    if polygon is None or len(polygon) < 3:
        return mask
    shifted = np.asarray(polygon, dtype=np.float32).copy()
    shifted[:, 0] -= left
    shifted[:, 1] -= top
    cv2.fillPoly(mask, [shifted.astype(np.int32)], 255)
    if mask.shape[:2] != shape[:2]:
        mask = cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return mask


class Segmenter:
    """One segmentation pass per frame, then a mask for each detection box."""

    def __init__(self, model=None, class_ids=None, conf=0.4, imgsz=320):
        self.model = model
        self.class_ids = class_ids
        self.conf = conf
        self.imgsz = imgsz
        self.instances = []
        self._warned = False

    def begin_frame(self, frame):
        self.instances = []
        if self.model is None:
            return
        try:
            kwargs = {"imgsz": self.imgsz, "conf": self.conf, "show": False, "save": False, "verbose": False}
            if self.class_ids is not None:
                kwargs["classes"] = self.class_ids
            result = self.model.predict(frame, **kwargs)[0]
            self.instances = instances_from_result(result)
            if not self.instances and not self._warned and getattr(result, "masks", None) is None:
                self._warned = True
                print(
                    "The segmentation model returned no masks. "
                    "Detection boxes are not used as masks. OpenCV GrabCut will try each crop.",
                    flush=True,
                )
        except Exception as exc:
            print(f"segmentation hiccup: {exc}", flush=True)
            self.instances = []

    def _matched_mask(self, xyxy, bounds, shape, class_name):
        best = None
        best_iou = 0.2
        for instance in self.instances:
            if class_name and instance["class_name"] != class_name:
                continue
            overlap = _iou(xyxy, instance["xyxy"])
            if overlap > best_iou:
                best = instance
                best_iou = overlap
        if best is None:
            return None
        return _rasterize(best["polygon"], bounds, shape)

    def isolate(self, frame, xyxy, class_name):
        """Return (crop, mask) or (crop, None) when the object cannot be separated."""
        crop, bounds = crop_window(frame, xyxy)
        if crop is None:
            return None, None
        mask = None
        if self.instances:
            mask = self._matched_mask(xyxy, bounds, crop.shape, class_name)
            if not mask_is_isolated(mask):
                mask = None
        if mask is None:
            mask = grabcut_mask(crop)
        if not mask_is_isolated(mask):
            return crop, None
        return crop, mask


def open_segmenter(explicit, class_names, conf, imgsz):
    """Load YOLO26n-seg when it is on disk. Otherwise GrabCut, and say so."""
    found = resolve_seg_path(explicit)
    if found is None:
        if explicit:
            print(
                f"No segmentation model at {explicit}. "
                "The detection model is not a mask. OpenCV GrabCut will try each crop.",
                flush=True,
            )
        else:
            print(
                "Isolating each crop with OpenCV GrabCut. "
                "A YOLO segmentation model is not loaded on its own, "
                "because that NCNN build can Bus-error on the Pi.",
                flush=True,
            )
        return Segmenter()
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        print(
            "ultralytics is not installed, so the segmentation model cannot run. "
            f"OpenCV GrabCut will try each crop. ({exc})",
            flush=True,
        )
        return Segmenter()
    from observatory.coco import resolve_class_ids
    model = YOLO(str(found))
    class_ids = None if class_names is None else resolve_class_ids(model.names, class_names)
    print(f"Segmentation model: {found}", flush=True)
    return Segmenter(model, class_ids=class_ids, conf=conf, imgsz=imgsz)
