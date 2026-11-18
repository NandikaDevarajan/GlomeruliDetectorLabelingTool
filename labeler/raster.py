##############################################################################################
# Purpose: The bridge between polygons and masks, which is what lets the brush and the eraser
# work on regions that were drawn with the polygon or freehand tools, and the other way round.
#
# A region is always stored as a polygon (see spec/architecture.md, 3.2). The brush and the
# eraser rasterise the region they are modifying, stamp into the mask, and trace the result
# back. The tracing is MaskPostProcessor from the repository root - the same connected
# components, hole filling and contour tracing the detector uses to turn model output into
# polygons, so a hand-painted region and a predicted one are the same kind of object.
##############################################################################################

import os
import sys

import numpy as np
from PIL import Image, ImageDraw

from . import geometry
from .config import MASK_MIN_COMPONENT_PIXELS, MASK_SIMPLIFY_TOLERANCE

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DETECTOR_DIR = os.path.join(_REPO_ROOT, "gdetector")
if _DETECTOR_DIR not in sys.path:
    sys.path.insert(0, _DETECTOR_DIR)

try:
    from maskpostprocessor import MaskPostProcessor
except ImportError as error:  # pragma: no cover - only hit if the tool is moved out of the repo
    raise ImportError(
        "The brush and eraser need maskpostprocessor.py from the detector application, "
        f"which was looked for in {_DETECTOR_DIR}. Keep the LabelingTool folder beside "
        "gdetector/ in the repository, or copy maskpostprocessor.py next to this file."
    ) from error

_STAMP_CACHE = {}


def polygon_to_mask(points, width, height):
    """Rasterise a closed ring into a boolean mask of the given size."""
    canvas = Image.new("1", (int(width), int(height)), 0)
    if points and len(points) >= 3:
        ImageDraw.Draw(canvas).polygon([(float(x), float(y)) for x, y in points], fill=1)
    return np.array(canvas, dtype=bool)


def polygons_to_mask(polygons, width, height):
    """Union of several rings into one mask."""
    canvas = Image.new("1", (int(width), int(height)), 0)
    draw = ImageDraw.Draw(canvas)
    for points in polygons:
        if points and len(points) >= 3:
            draw.polygon([(float(x), float(y)) for x, y in points], fill=1)
    return np.array(canvas, dtype=bool)


def mask_to_polygons(mask, tolerance=MASK_SIMPLIFY_TOLERANCE,
                     min_pixels=MASK_MIN_COMPONENT_PIXELS):
    """Every component of a mask as a simplified ring in (x, y) image coordinates.

    Components smaller than min_pixels are dropped as stray paint. Holes are filled: a region
    with a hole in it cannot be expressed as a single ring, and a glomerulus does not have one.

    The traced boundary is simplified but not smoothed. Smoothing would pull the outline
    inside what the user painted, and a brush should put the boundary where the hand put it.
    """
    if mask is None or not mask.any():
        return []

    labels, count = MaskPostProcessor.label_components(mask)
    polygons = []
    for index in range(1, count + 1):
        component = labels == index
        if int(component.sum()) < min_pixels:
            continue
        component = MaskPostProcessor.fill_holes(component)
        contour = MaskPostProcessor.trace_outer_contour(component)
        if len(contour) < 3:
            continue
        # trace_outer_contour works in (row, column); the rest of the tool is (x, y).
        ring = [(float(x), float(y)) for y, x in contour]
        ring = geometry.drop_duplicate_points(ring)
        ring = geometry.simplify(ring, tolerance)
        if len(ring) >= 3 and geometry.polygon_area(ring) > 0:
            polygons.append(ring)

    polygons.sort(key=geometry.polygon_area, reverse=True)
    return polygons


def _disc(radius):
    """Cached boolean disc of the given radius, so a stamp is a slice assignment."""
    radius = int(max(1, radius))
    stamp = _STAMP_CACHE.get(radius)
    if stamp is None:
        size = radius * 2 + 1
        offsets = np.arange(size) - radius
        yy, xx = np.meshgrid(offsets, offsets, indexing="ij")
        stamp = (xx * xx + yy * yy) <= radius * radius
        _STAMP_CACHE[radius] = stamp
    return stamp


def stamp_disc(mask, x, y, radius, value=True):
    """Paint one circular stamp into a mask, clipped at the edges."""
    radius = int(max(1, radius))
    stamp = _disc(radius)
    height, width = mask.shape
    cx, cy = int(round(x)), int(round(y))

    left, top = cx - radius, cy - radius
    right, bottom = left + stamp.shape[1], top + stamp.shape[0]

    # Clip the target rectangle to the mask, and the stamp by the same amount.
    sx0 = max(0, -left)
    sy0 = max(0, -top)
    sx1 = stamp.shape[1] - max(0, right - width)
    sy1 = stamp.shape[0] - max(0, bottom - height)
    if sx0 >= sx1 or sy0 >= sy1:
        return

    target = mask[max(0, top):min(height, bottom), max(0, left):min(width, right)]
    piece = stamp[sy0:sy1, sx0:sx1]
    if value:
        target |= piece
    else:
        target &= ~piece


def stamp_segment(mask, x0, y0, x1, y1, radius, value=True):
    """Paint along a line, so a fast drag does not leave a dotted trail.

    Steps at half the radius, which overlaps consecutive stamps enough that the union has no
    scalloping on its edge.
    """
    radius = int(max(1, radius))
    distance = float(np.hypot(x1 - x0, y1 - y0))
    steps = max(1, int(distance / max(1.0, radius * 0.5)))
    for step in range(steps + 1):
        t = step / float(steps)
        stamp_disc(mask, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, radius, value)
