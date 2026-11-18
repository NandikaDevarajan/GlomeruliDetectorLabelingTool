##############################################################################################
# Purpose: Defaults, limits and the small settings file that remembers them between sessions.
#
# Nothing here is required for the application to run. A missing or unreadable settings file
# falls back to the defaults silently, because losing a brush size should never stop someone
# from opening an image.
##############################################################################################

import json
import os

TOOL_NAME = "Histology Labeler"
TOOL_VERSION = "1.0"

# Marker written into every sidecar. storage.py refuses to overwrite a file in the sidecar
# position that does not carry it, so a stray JSON of someone else's is never clobbered.
SIDECAR_FORMAT = "histology-labeler"
SIDECAR_VERSION = 1

# The sidecar sits beside the image under the image's own name. Change this one string if a
# plain ".json" ever collides with something else in the image folders.
SIDECAR_SUFFIX = ".json"

SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(PACKAGE_DIR)
REPO_ROOT = os.path.dirname(TOOL_DIR)
SETTINGS_PATH = os.path.join(TOOL_DIR, "settings.json")

DEFAULT_CLASSES = [
    {"id": 1, "name": "Glomerulus", "color": "#E6194B"},
    {"id": 2, "name": "Sclerotic Glomerulus", "color": "#3CB44B"},
    {"id": 3, "name": "Partial Glomerulus", "color": "#4363D8"},
    {"id": 4, "name": "Other Region", "color": "#F58231"},
]

# Offered when the user adds a class, in order, skipping any colour already in use.
PALETTE = [
    "#E6194B", "#3CB44B", "#4363D8", "#F58231", "#911EB4", "#42D4F4",
    "#F032E6", "#BFEF45", "#FABED4", "#469990", "#DCBEFF", "#9A6324",
    "#FFFAC8", "#800000", "#AAFFC3", "#808000", "#FFD8B1", "#000075",
]

MIN_ZOOM = 0.02
MAX_ZOOM = 32.0
ZOOM_STEP = 1.15

# Freehand: minimum travel in screen pixels before another point is recorded, and the
# Ramer-Douglas-Peucker tolerance in image pixels applied once the stroke is finished.
FREEHAND_MIN_SCREEN_STEP = 2.0
FREEHAND_SIMPLIFY_TOLERANCE = 1.0

# Mask-derived polygons (brush and eraser) are simplified harder: a painted boundary is
# already blocky, and tracing it literally produces a vertex per pixel step.
MASK_SIMPLIFY_TOLERANCE = 1.5
MASK_MIN_COMPONENT_PIXELS = 50

VERTEX_HIT_RADIUS = 7.0
VERTEX_HANDLE_SIZE = 4
CLOSE_POLYGON_RADIUS = 10.0

DEFAULT_BRUSH_RADIUS = 20
MIN_BRUSH_RADIUS = 2
MAX_BRUSH_RADIUS = 300

UNDO_DEPTH = 80

DEFAULTS = {
    "classes": DEFAULT_CLASSES,
    "active_class_id": 1,
    "brush_radius": DEFAULT_BRUSH_RADIUS,
    "overlay_opacity": 0.35,
    "show_fills": True,
    "show_outlines": True,
    "show_labels": True,
    "last_folder": "",
    "window": "1400x900",
}


def load_settings():
    """Settings from disk merged over the defaults. Never raises."""
    settings = dict(DEFAULTS)
    settings["classes"] = [dict(entry) for entry in DEFAULT_CLASSES]
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS:
                    settings[key] = value
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    """Best effort. A settings file that cannot be written is not worth a dialog."""
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2)
    except OSError:
        pass
