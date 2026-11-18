##############################################################################################
# Purpose: Open an image for annotation, and work out how big a pixel is where the file says so.
#
# Two details matter more than they look:
#
#   * Only the first frame of a multi-page TIFF is used. The microscopy TIFFs in this
#     repository carry reduced-size thumbnails as later frames, and annotating one would
#     record coordinates against the wrong dimensions.
#   * Pixel size is read from OME-XML when the file carries it. The new brightfield images
#     declare 0.85 um/px while the detector's PIXEL_TO_MICRON_FACTOR is 0.7634, so an area
#     measured with the wrong one is out by about a quarter.
##############################################################################################

import os
import re

from PIL import Image

from .config import SUPPORTED_EXTENSIONS

# Pillow refuses very large images by default as a decompression-bomb guard. Whole-slide
# scans legitimately exceed it, and these files are the user's own.
Image.MAX_IMAGE_PIXELS = None

_TIFF_IMAGE_DESCRIPTION = 270
_TIFF_X_RESOLUTION = 282
_TIFF_RESOLUTION_UNIT = 296

_PHYSICAL_SIZE_X = re.compile(r'PhysicalSizeX\s*=\s*"([0-9.eE+-]+)"')
_PHYSICAL_SIZE_UNIT = re.compile(r'PhysicalSizeXUnit\s*=\s*"([^"]+)"')

# Everything is converted to microns per pixel.
_UNIT_TO_MICRONS = {
    "nm": 0.001, "nanometer": 0.001,
    "um": 1.0, "µm": 1.0, "micron": 1.0, "micrometer": 1.0,
    "mm": 1000.0, "millimeter": 1000.0,
    "cm": 10000.0, "centimeter": 10000.0,
    "m": 1000000.0, "meter": 1000000.0,
}


class LoadedImage:
    def __init__(self, path, image, pixel_size_um=None, frame_count=1):
        self.path = path
        self.image = image
        self.width, self.height = image.size
        self.pixel_size_um = pixel_size_um
        self.frame_count = frame_count

    @property
    def name(self):
        return os.path.basename(self.path)


def is_supported(path):
    return path.lower().endswith(SUPPORTED_EXTENSIONS)


def list_folder(folder):
    """Supported images directly inside a folder, sorted by name. Sub-folders are not entered."""
    try:
        names = sorted(name for name in os.listdir(folder) if is_supported(name))
    except OSError:
        return []
    return [os.path.join(folder, name) for name in names
            if os.path.isfile(os.path.join(folder, name))]


def _pixel_size_from_description(description):
    """Microns per pixel from an OME-XML ImageDescription, or None."""
    if not description:
        return None
    if isinstance(description, bytes):
        description = description.decode("utf-8", "ignore")
    match = _PHYSICAL_SIZE_X.search(description)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    if value <= 0:
        return None
    unit_match = _PHYSICAL_SIZE_UNIT.search(description)
    unit = (unit_match.group(1) if unit_match else "um").strip().lower()
    return value * _UNIT_TO_MICRONS.get(unit, 1.0)


def _pixel_size_from_resolution(info):
    """Microns per pixel from the TIFF resolution tags, when they mean anything.

    Only a resolution given in centimetres is trusted. Inch-based values are usually the
    scanner software writing a 96 dpi screen default, which says nothing about the specimen,
    and reading it as a scale would silently produce areas that are wrong by a factor of ten.
    """
    unit = info.get(_TIFF_RESOLUTION_UNIT)
    if unit != 3:
        return None
    resolution = info.get(_TIFF_X_RESOLUTION)
    if resolution is None:
        return None
    try:
        value = float(resolution)
    except (TypeError, ValueError):
        try:
            value = float(resolution[0]) / float(resolution[1])
        except (TypeError, ValueError, ZeroDivisionError, IndexError):
            return None
    if value <= 0:
        return None
    return 10000.0 / value


def read_pixel_size(path):
    """Microns per pixel declared by the file, or None when it does not say."""
    try:
        with Image.open(path) as image:
            image.seek(0)
            info = getattr(image, "tag_v2", None) or {}
            size = _pixel_size_from_description(info.get(_TIFF_IMAGE_DESCRIPTION))
            if size is None:
                size = _pixel_size_from_description(image.info.get("description"))
            if size is None:
                size = _pixel_size_from_resolution(info)
            return size
    except (OSError, ValueError):
        return None


def load(path):
    """Open the first frame as RGB, with its declared pixel size if it has one."""
    with Image.open(path) as handle:
        frame_count = getattr(handle, "n_frames", 1)
        handle.seek(0)
        info = getattr(handle, "tag_v2", None) or {}
        pixel_size = _pixel_size_from_description(info.get(_TIFF_IMAGE_DESCRIPTION))
        if pixel_size is None:
            pixel_size = _pixel_size_from_description(handle.info.get("description"))
        if pixel_size is None:
            pixel_size = _pixel_size_from_resolution(info)
        # copy() detaches the frame from the file handle, which the with block is about to close.
        image = handle.convert("RGB").copy()
    return LoadedImage(path, image, pixel_size, frame_count)
