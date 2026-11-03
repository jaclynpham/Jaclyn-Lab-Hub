"""Turn a saved crop into ASCII. No art library and no language model.

OpenCV grayscale is 0 for black and 255 for white. The ramp runs the other way:
a space is empty paper, and the last character is the most ink.
"""
import cv2

# Courier New is about 0.6em wide and one em tall when line-height is 1.
# Rows are scaled by this ratio so a circle does not come out tall and thin.
CHAR_ASPECT = 0.6

# Light and sparse, then dark and dense. The Bourke ramp, reversed.
DENSITY_RAMP = (
    r" .'`^" + '"' + r",:;Il!i><~+_-?][}{1)(|\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
)


def image_to_ascii(image, cols=48, char_aspect=CHAR_ASPECT, mask=None):
    """Map an OpenCV image to a character grid.

    `image` is grayscale or BGR, as cv2.imread and the camera return it.
    `cols` is the width of the grid. The height follows the picture's aspect
    ratio times `char_aspect` (character width divided by character height).
    Where `mask` is background, the cell is a space so the paper shows through.
    """
    if image is None or getattr(image, "size", 0) == 0:
        return ""
    if image.ndim == 2:
        gray = image
    elif image.shape[2] == 4:
        gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    if width < 1 or height < 1:
        return ""
    cols = max(1, int(cols))
    rows = max(1, int(round(cols * (height / float(width)) * float(char_aspect))))
    small = cv2.resize(gray, (cols, rows), interpolation=cv2.INTER_AREA)
    foreground = None
    if mask is not None and getattr(mask, "size", 0) != 0:
        gray_mask = mask if mask.ndim == 2 else cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray_mask, (cols, rows), interpolation=cv2.INTER_AREA)
        foreground = resized >= 128
    last = len(DENSITY_RAMP) - 1
    lines = []
    for y, row in enumerate(small):
        chars = []
        for x, pixel in enumerate(row):
            if foreground is not None and not bool(foreground[y, x]):
                chars.append(" ")
                continue
            brightness = int(pixel)
            index = (255 - brightness) * last // 255
            chars.append(DENSITY_RAMP[index])
        lines.append("".join(chars))
    return "\n".join(lines)
