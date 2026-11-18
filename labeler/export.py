##############################################################################################
# Purpose: Turn a working set of annotated images into the formats a training pipeline reads.
#
# The one worth understanding is export_training_pair. It writes a Data/Train pair in exactly
# the convention ModelTrainer/prepare_dataset.py in this repository already consumes: a clean
# of the image, and a copy with every region outlined in pure red. That script recovers masks
# by diffing the two and keeping the red-dominant changed pixels, which is how the existing
# model's own drawings were turned back into training data. Exporting in that shape means a
# newly labelled stain is trainable with no change to the pipeline at all.
##############################################################################################

import json
import os
import shutil
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw

from . import geometry, imageloader
from .config import SIDECAR_FORMAT, TOOL_NAME, TOOL_VERSION

# polygondrawer.py draws outlines in pure red and areas in yellow; prepare_dataset.py looks
# for exactly that red. These two constants are a contract with those two files.
OUTLINE_COLOR = (255, 0, 0)
LABEL_COLOR = (255, 255, 0)


def _annotated(items):
    return [(path, document) for path, document in items
            if document is not None and document.annotations]


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def export_coco(items, class_table, out_dir):
    """COCO instance segmentation, one annotations.json for the whole set."""
    os.makedirs(out_dir, exist_ok=True)
    images, annotations = [], []
    annotation_index = 1

    for image_index, (path, document) in enumerate(_annotated(items), start=1):
        images.append({
            "id": image_index,
            "file_name": os.path.basename(path),
            "width": document.width,
            "height": document.height,
        })
        for annotation in document.annotations:
            if len(annotation.points) < 3:
                continue
            box = annotation.bounding_box()
            flat = [round(float(value), 2) for point in annotation.points for value in point]
            annotations.append({
                "id": annotation_index,
                "image_id": image_index,
                "category_id": annotation.class_id,
                "segmentation": [flat],
                "bbox": [round(box[0], 2), round(box[1], 2),
                         round(box[2] - box[0], 2), round(box[3] - box[1], 2)],
                "area": round(annotation.area_pixels, 2),
                "iscrowd": 0,
            })
            annotation_index += 1

    payload = {
        "info": {
            "description": f"Exported by {TOOL_NAME} {TOOL_VERSION}",
            "date_created": datetime.now().isoformat(timespec="seconds"),
        },
        "licenses": [],
        "images": images,
        "annotations": annotations,
        "categories": [{"id": entry.id, "name": entry.name, "supercategory": "region"}
                       for entry in class_table],
    }
    target = os.path.join(out_dir, "annotations.json")
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return f"{len(annotations)} regions from {len(images)} images -> {target}"


def export_yolo(items, class_table, out_dir):
    """YOLO segmentation: labels/<stem>.txt with normalised coordinates, plus the class list."""
    labels_dir = os.path.join(out_dir, "labels")
    os.makedirs(labels_dir, exist_ok=True)

    written = 0
    for path, document in _annotated(items):
        lines = []
        for annotation in document.annotations:
            if len(annotation.points) < 3 or not document.width or not document.height:
                continue
            # YOLO indexes classes densely from zero, so the position in the table is used
            # rather than the class id, which may be sparse after a class is deleted.
            index = class_table.index_of(annotation.class_id)
            if index < 0:
                continue
            values = []
            for x, y in annotation.points:
                values.append(min(max(x / document.width, 0.0), 1.0))
                values.append(min(max(y / document.height, 0.0), 1.0))
            lines.append(f"{index} " + " ".join(f"{value:.6f}" for value in values))
        if not lines:
            continue
        with open(os.path.join(labels_dir, _stem(path) + ".txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        written += 1

    names = [entry.name for entry in class_table]
    with open(os.path.join(out_dir, "classes.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(names) + "\n")
    with open(os.path.join(out_dir, "data.yaml"), "w", encoding="utf-8") as handle:
        handle.write(f"nc: {len(names)}\n")
        handle.write("names: [" + ", ".join(f"'{name}'" for name in names) + "]\n")
    return f"{written} label files -> {labels_dir}"


def export_masks(items, class_table, out_dir):
    """One binary PNG per region, plus a combined mask per class, per image."""
    os.makedirs(out_dir, exist_ok=True)
    written = 0

    for path, document in _annotated(items):
        if not document.width or not document.height:
            continue
        folder = os.path.join(out_dir, _stem(path))
        os.makedirs(folder, exist_ok=True)
        per_class = {}

        for annotation in document.annotations:
            if len(annotation.points) < 3:
                continue
            canvas = Image.new("L", (document.width, document.height), 0)
            ImageDraw.Draw(canvas).polygon(
                [(float(x), float(y)) for x, y in annotation.points], fill=255)
            entry = class_table.get(annotation.class_id)
            name = _safe(entry.name if entry else str(annotation.class_id))
            canvas.save(os.path.join(folder, f"region_{annotation.id:03d}_{name}.png"))
            written += 1

            combined = per_class.get(name)
            array = np.array(canvas, dtype=np.uint8)
            per_class[name] = array if combined is None else np.maximum(combined, array)

        for name, array in per_class.items():
            Image.fromarray(array).save(os.path.join(folder, f"class_{name}.png"))

    return f"{written} region masks -> {out_dir}"


def export_project(items, class_table, out_path):
    """Every sidecar in the set collected into one file, so a whole job is one artefact."""
    images = {}
    for path, document in _annotated(items):
        images[os.path.basename(path)] = {
            "image": {
                "file": os.path.basename(path),
                "width": document.width,
                "height": document.height,
                "pixel_size_um": document.pixel_size_um,
            },
            "annotations": [a.to_dict(class_table) for a in document.annotations],
        }
    payload = {
        "format": SIDECAR_FORMAT + "-project",
        "version": 1,
        "exported": datetime.now().isoformat(timespec="seconds"),
        "classes": class_table.to_list(),
        "images": images,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return f"{len(images)} images -> {out_path}"


def export_training_pair(items, class_table, out_dir, class_ids=None):
    """Data/ and Train/ folders in the convention ModelTrainer/prepare_dataset.py reads.

    Data holds a byte-for-byte copy of the original image. Train holds the first frame with
    every region outlined in pure red and its area written in yellow, which is what
    polygondrawer.py produces for the model's own detections. Only the first frame is written
    to Train, and prepare_dataset.py reads frame zero of both, so the two always line up.

    class_ids restricts the export to particular classes, for the common case of training a
    single-class detector from a file that also carries other kinds of region.
    """
    data_dir = os.path.join(out_dir, "Data")
    train_dir = os.path.join(out_dir, "Train")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(train_dir, exist_ok=True)

    written, regions = 0, 0
    skipped = []
    for path, document in _annotated(items):
        selected = [a for a in document.annotations
                    if len(a.points) >= 3 and (class_ids is None or a.class_id in class_ids)]
        if not selected:
            continue

        name = os.path.basename(path)
        try:
            loaded = imageloader.load(path)
        except (OSError, ValueError) as error:
            skipped.append(f"{name}: {error}")
            continue

        drawing = loaded.image.copy()
        draw = ImageDraw.Draw(drawing)
        for annotation in selected:
            points = [(float(x), float(y)) for x, y in annotation.points]
            label_x, label_y = geometry.bounding_box(points)[:2]
            if loaded.pixel_size_um:
                area = annotation.area_pixels * loaded.pixel_size_um ** 2
                text = f"{area:.2f} um^2"
            else:
                text = f"{annotation.area_pixels:.0f} px"
            draw.text((label_x + 5, label_y - 15), text, fill=LABEL_COLOR)
            draw.polygon(points, outline=OUTLINE_COLOR)
            regions += 1

        # Copy rather than re-encode, so Data is bit-identical to what the scanner produced.
        destination = os.path.join(data_dir, name)
        if os.path.abspath(destination) != os.path.abspath(path):
            shutil.copy2(path, destination)
        drawing.save(os.path.join(train_dir, name))
        written += 1

    message = f"{regions} regions on {written} images -> {out_dir}"
    if skipped:
        message += f" ({len(skipped)} skipped: {skipped[0]})"
    return message


def _safe(name):
    """Make a class name usable as a file name."""
    cleaned = "".join(character if character.isalnum() or character in "-_" else "_"
                      for character in name)
    return cleaned.strip("_") or "class"
