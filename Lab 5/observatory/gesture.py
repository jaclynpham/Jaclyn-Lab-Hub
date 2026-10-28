"""Optional Quiet Coyote start, using the distances from hand_pose.py.

Command-line duration and Ctrl-C do not need this. The watch still runs if
MediaPipe cannot be imported.
"""
import math


def is_quiet_coyote(lm_list):
    """The Part C rule: thumb-to-index and the other fingertip distances.

    Landmark ids match HandTrackingModule: 4 thumb, 8 index, 12 middle,
    16 ring, 20 pinky. Each item is [id, x, y] in pixels.
    """
    if not lm_list or len(lm_list) < 21:
        return False
    points = {}
    for item in lm_list:
        if len(item) < 3:
            return False
        points[item[0]] = (item[1], item[2])
    if not {4, 8, 12, 16, 20} <= set(points):
        return False

    def dist(a, b):
        return math.hypot(points[a][0] - points[b][0], points[a][1] - points[b][1])

    thumb_index = dist(4, 8)
    index_middle = dist(8, 12)
    middle_ring = dist(12, 16)
    ring_pinky = dist(16, 20)
    thumb_ring = dist(4, 16)
    return (
        thumb_index > 100
        and index_middle > 100
        and middle_ring < 100
        and ring_pinky > 100
        and thumb_ring < 100
    )


def try_hand_detector():
    try:
        import HandTrackingModule as htm
        return htm.handDetector(detectionCon=0.7)
    except Exception as exc:
        print(f"Quiet Coyote is unavailable ({exc}). The timer still runs.", flush=True)
        return None


def landmarks_from(detector, frame):
    drawn = detector.findHands(frame, draw=False)
    return detector.findPosition(drawn, draw=False)
