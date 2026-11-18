##############################################################################################
# Purpose: The data the application is actually about - classes, annotations, and the document
# holding the annotations for one image.
#
# No user interface, no file access. Everything here can be built, changed and inspected from
# a script, which is what makes the rest of the tool testable without a display.
##############################################################################################

import copy

from . import geometry


class AnnotationClass:
    """A named category with a colour, for example Glomerulus."""

    def __init__(self, class_id, name, color):
        self.id = int(class_id)
        self.name = str(name)
        self.color = str(color)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "color": self.color}

    @classmethod
    def from_dict(cls, data):
        return cls(data.get("id", 0), data.get("name", "Class"), data.get("color", "#E6194B"))

    def rgb(self):
        """(r, g, b) from the stored #RRGGBB, falling back to mid grey if it is malformed."""
        text = self.color.lstrip("#")
        if len(text) != 6:
            return 128, 128, 128
        try:
            return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
        except ValueError:
            return 128, 128, 128


class ClassTable:
    """The ordered list of classes, and the only place class ids are handed out."""

    def __init__(self, classes=None):
        self.classes = list(classes or [])

    # ------------------------------------------------------------------ lookup

    def __len__(self):
        return len(self.classes)

    def __iter__(self):
        return iter(self.classes)

    def get(self, class_id):
        for entry in self.classes:
            if entry.id == int(class_id):
                return entry
        return None

    def index_of(self, class_id):
        """Dense position in the table. YOLO needs indices from zero, not sparse ids."""
        for index, entry in enumerate(self.classes):
            if entry.id == int(class_id):
                return index
        return -1

    def by_name(self, name):
        for entry in self.classes:
            if entry.name.lower() == str(name).lower():
                return entry
        return None

    def next_id(self):
        return max((entry.id for entry in self.classes), default=0) + 1

    def next_color(self, palette):
        used = {entry.color.upper() for entry in self.classes}
        for color in palette:
            if color.upper() not in used:
                return color
        return palette[len(self.classes) % len(palette)]

    # ----------------------------------------------------------------- mutation

    def add(self, name, color):
        entry = AnnotationClass(self.next_id(), name, color)
        self.classes.append(entry)
        return entry

    def remove(self, class_id):
        self.classes = [entry for entry in self.classes if entry.id != int(class_id)]

    def adopt(self, entry):
        """Take in a class from a sidecar written elsewhere.

        Sidecars carry their own class list so they stay self-describing. Opening one written
        on another machine should not silently drop its classes, and must not let an incoming
        id collide with a different local class of the same id.
        """
        existing = self.get(entry.id)
        if existing is None:
            same_name = self.by_name(entry.name)
            if same_name is not None:
                return same_name
            self.classes.append(AnnotationClass(entry.id, entry.name, entry.color))
            return self.classes[-1]
        if existing.name.lower() == entry.name.lower():
            return existing
        # Same id, different meaning: keep ours and give the incoming one a fresh id.
        same_name = self.by_name(entry.name)
        if same_name is not None:
            return same_name
        return self.add(entry.name, entry.color)

    def to_list(self):
        return [entry.to_dict() for entry in self.classes]

    @classmethod
    def from_list(cls, data):
        return cls([AnnotationClass.from_dict(entry) for entry in (data or [])])


class Annotation:
    """One outlined region. Points are a closed ring in image pixels, first point not repeated."""

    def __init__(self, annotation_id, class_id, points, notes="", visible=True):
        self.id = int(annotation_id)
        self.class_id = int(class_id)
        self.points = [(float(x), float(y)) for x, y in points]
        self.notes = str(notes)
        self.visible = bool(visible)

    @property
    def area_pixels(self):
        return geometry.polygon_area(self.points)

    def bounding_box(self):
        return geometry.bounding_box(self.points)

    def contains(self, point):
        return geometry.point_in_polygon(point, self.points)

    def clone(self):
        return Annotation(self.id, self.class_id, list(self.points), self.notes, self.visible)

    def to_dict(self, class_table=None):
        entry = class_table.get(self.class_id) if class_table else None
        return {
            "id": self.id,
            "class_id": self.class_id,
            "class_name": entry.name if entry else "",
            "points": [[round(x, 2), round(y, 2)] for x, y in self.points],
            "area_pixels": round(self.area_pixels, 2),
            "visible": self.visible,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data.get("id", 0),
            data.get("class_id", 1),
            [(p[0], p[1]) for p in data.get("points", [])],
            data.get("notes", ""),
            data.get("visible", True),
        )


class Document:
    """The annotations for one image, plus what is needed to interpret them."""

    def __init__(self, image_name="", width=0, height=0, pixel_size_um=None):
        self.image_name = image_name
        self.width = int(width)
        self.height = int(height)
        self.pixel_size_um = pixel_size_um
        self.annotations = []
        self.created = None
        self.modified = None
        # Set when a sidecar records dimensions that do not match the image on disk.
        self.size_mismatch = None

    # ------------------------------------------------------------------ access

    def __len__(self):
        return len(self.annotations)

    def get(self, annotation_id):
        # "nothing selected" is a normal state, so None is answered rather than rejected.
        if annotation_id is None:
            return None
        for annotation in self.annotations:
            if annotation.id == int(annotation_id):
                return annotation
        return None

    def next_id(self):
        return max((a.id for a in self.annotations), default=0) + 1

    def counts_by_class(self):
        counts = {}
        for annotation in self.annotations:
            counts[annotation.class_id] = counts.get(annotation.class_id, 0) + 1
        return counts

    def pick(self, point):
        """Topmost visible region containing the point.

        Last drawn wins, which matches what the user sees: later regions paint over earlier
        ones. Among overlapping candidates the smallest is preferred, so a region nested
        inside another stays reachable.
        """
        candidates = [a for a in self.annotations if a.visible and a.contains(point)]
        if not candidates:
            return None
        return min(candidates, key=lambda a: (a.area_pixels, -a.id))

    # ---------------------------------------------------------------- mutation

    def add(self, class_id, points, notes="", visible=True):
        annotation = Annotation(self.next_id(), class_id, points, notes, visible)
        self.annotations.append(annotation)
        return annotation

    def remove(self, annotation_id):
        if annotation_id is None:
            return False
        before = len(self.annotations)
        self.annotations = [a for a in self.annotations if a.id != int(annotation_id)]
        return len(self.annotations) != before

    def replace_points(self, annotation_id, points):
        annotation = self.get(annotation_id)
        if annotation is not None:
            annotation.points = [(float(x), float(y)) for x, y in points]
        return annotation

    # ------------------------------------------------------------------ history

    def snapshot(self):
        """State undo restores. The image is not part of it - only the annotations are."""
        return copy.deepcopy(self.annotations)

    def restore(self, snapshot):
        self.annotations = copy.deepcopy(snapshot)
