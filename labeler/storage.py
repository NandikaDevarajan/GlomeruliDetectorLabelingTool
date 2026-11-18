##############################################################################################
# Purpose: Read and write the JSON sidecar that sits beside each image under the image's name.
#
# Two rules protect work that is already on disk:
#
#   1. A file in the sidecar position is only ever overwritten if it carries this tool's
#      format marker. Someone else's "71121_1.json" is left alone and reported.
#   2. Saving writes a temporary file in the same folder and then replaces the original with
#      os.replace, which is atomic on Windows and POSIX alike. A crash mid-write leaves the
#      previous sidecar intact rather than a half-written one.
##############################################################################################

import json
import os
from datetime import datetime

from .config import SIDECAR_FORMAT, SIDECAR_SUFFIX, SIDECAR_VERSION
from .model import AnnotationClass, Annotation, Document


class SidecarError(Exception):
    """Raised when a sidecar cannot be read, or must not be written over."""


def sidecar_path(image_path):
    """Beside the image, named after the image: 'x.tif' -> 'x.json'."""
    folder = os.path.dirname(os.path.abspath(image_path))
    stem = os.path.splitext(os.path.basename(image_path))[0]
    return os.path.join(folder, stem + SIDECAR_SUFFIX)


def has_sidecar(image_path):
    return os.path.exists(sidecar_path(image_path))


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except ValueError as error:
        raise SidecarError(f"{os.path.basename(path)} is not valid JSON ({error}).")
    except OSError as error:
        raise SidecarError(f"{os.path.basename(path)} could not be read ({error}).")


def _check_ours(data, path):
    if not isinstance(data, dict) or data.get("format") != SIDECAR_FORMAT:
        raise SidecarError(
            f"{os.path.basename(path)} already exists and was not written by this tool. "
            f"Move or rename it before annotating this image, so nothing is overwritten."
        )


def peek_count(image_path):
    """How many regions a sidecar holds, without building a document. 0 if unreadable.

    Used to show annotation status for a whole folder, where one bad file must not stop the
    list from being drawn.
    """
    path = sidecar_path(image_path)
    if not os.path.exists(path):
        return 0
    try:
        data = _read_json(path)
        if not isinstance(data, dict) or data.get("format") != SIDECAR_FORMAT:
            return 0
        return len(data.get("annotations", []))
    except SidecarError:
        return 0


def load_sidecar(image_path, class_table, width=0, height=0, pixel_size_um=None):
    """Document for this image: from its sidecar if there is one, otherwise empty.

    Any classes the sidecar carries that the local table does not know are adopted, so a
    sidecar annotated on another machine opens with its own class names intact.
    """
    document = Document(os.path.basename(image_path), width, height, pixel_size_um)
    path = sidecar_path(image_path)
    if not os.path.exists(path):
        return document

    data = _read_json(path)
    _check_ours(data, path)

    # Resolve the sidecar's class ids onto the local table before reading annotations.
    remap = {}
    for entry in data.get("classes", []):
        incoming = AnnotationClass.from_dict(entry)
        resolved = class_table.adopt(incoming)
        remap[incoming.id] = resolved.id

    image_block = data.get("image", {})
    stored_width = int(image_block.get("width", 0) or 0)
    stored_height = int(image_block.get("height", 0) or 0)
    if width and height and stored_width and stored_height:
        if (stored_width, stored_height) != (width, height):
            document.size_mismatch = (stored_width, stored_height)
    elif stored_width and stored_height:
        # Called without opening the image, which is how export and validation read the rest
        # of a working set. The sidecar's own dimensions are then the only ones available.
        document.width, document.height = stored_width, stored_height
    if image_block.get("pixel_size_um") and not pixel_size_um:
        document.pixel_size_um = float(image_block["pixel_size_um"])

    fallback_class = class_table.classes[0].id if len(class_table) else 1
    for entry in data.get("annotations", []):
        annotation = Annotation.from_dict(entry)
        annotation.class_id = remap.get(annotation.class_id, annotation.class_id)
        if class_table.get(annotation.class_id) is None:
            annotation.class_id = fallback_class
        if len(annotation.points) >= 3:
            document.annotations.append(annotation)

    document.created = data.get("created")
    document.modified = data.get("modified")
    return document


def save_sidecar(image_path, document, class_table):
    """Write the sidecar, or remove it when the last region has been deleted.

    Returns the path written, the path removed, or None if there was nothing to do.
    """
    path = sidecar_path(image_path)

    if not document.annotations:
        # An image with no regions carries no sidecar, so an emptied image does not leave an
        # empty file behind that later reads as "annotated, zero regions".
        if os.path.exists(path):
            data = _read_json(path)
            _check_ours(data, path)
            try:
                os.remove(path)
            except OSError as error:
                raise SidecarError(f"Could not remove {os.path.basename(path)} ({error}).")
            return path
        return None

    if os.path.exists(path):
        _check_ours(_read_json(path), path)

    now = datetime.now().isoformat(timespec="seconds")
    used_class_ids = {a.class_id for a in document.annotations}
    payload = {
        "format": SIDECAR_FORMAT,
        "version": SIDECAR_VERSION,
        "created": document.created or now,
        "modified": now,
        "image": {
            "file": document.image_name or os.path.basename(image_path),
            "width": document.width,
            "height": document.height,
            "pixel_size_um": document.pixel_size_um,
        },
        "classes": [entry.to_dict() for entry in class_table if entry.id in used_class_ids],
        "annotations": [a.to_dict(class_table) for a in document.annotations],
    }

    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise SidecarError(f"Could not write {os.path.basename(path)} ({error}).")

    document.created = payload["created"]
    document.modified = now
    return path
