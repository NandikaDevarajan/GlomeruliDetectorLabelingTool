##############################################################################################
# Purpose: The checks that run before an export, and on demand.
#
# Severity is the point of this module. An error is something that will break a consumer or
# quietly poison a training run; a warning is something a person should look at but which is
# often perfectly correct. A glomerulus running off the edge of a field is normal, and
# flagging it as an error would only teach the user to click past the dialog.
##############################################################################################

import math

from . import geometry

ERROR = "error"
WARNING = "warning"

# Below this many square pixels a region is a collapsed ring, not a small region.
MIN_SENSIBLE_AREA = 4.0


class Finding:
    def __init__(self, severity, message, image_path=None, annotation_id=None):
        self.severity = severity
        self.message = message
        self.image_path = image_path
        self.annotation_id = annotation_id

    @property
    def is_error(self):
        return self.severity == ERROR

    def __repr__(self):
        return f"<{self.severity}: {self.message}>"


def validate_document(document, image_path=None):
    """Every finding for one image, errors first."""
    findings = []
    seen_ids = set()

    for annotation in document.annotations:
        reference = annotation.id

        if reference in seen_ids:
            findings.append(Finding(ERROR, f"Region {reference}: duplicate region id",
                                    image_path, reference))
        seen_ids.add(reference)

        points = annotation.points
        distinct = geometry.drop_duplicate_points(points)
        if len(distinct) < 3:
            findings.append(Finding(ERROR,
                                    f"Region {reference}: fewer than three distinct points",
                                    image_path, reference))
            continue

        if any(not math.isfinite(value) for point in points for value in point):
            findings.append(Finding(ERROR, f"Region {reference}: non-finite coordinate",
                                    image_path, reference))
            continue

        area = annotation.area_pixels
        if area < MIN_SENSIBLE_AREA:
            findings.append(Finding(ERROR, f"Region {reference}: area is {area:.1f} px",
                                    image_path, reference))
            continue

        box = annotation.bounding_box()
        if document.width and document.height:
            fully_outside = (box[2] <= 0 or box[0] >= document.width or
                             box[3] <= 0 or box[1] >= document.height)
            partly_outside = (box[0] < 0 or box[1] < 0 or
                              box[2] > document.width or box[3] > document.height)
            if fully_outside:
                findings.append(Finding(ERROR,
                                        f"Region {reference}: entirely outside the image",
                                        image_path, reference))
                continue
            if partly_outside:
                # Expected for a structure cut by the edge of the field, so a warning.
                findings.append(Finding(WARNING,
                                        f"Region {reference}: extends beyond the image edge",
                                        image_path, reference))

        if geometry.is_self_intersecting(points):
            findings.append(Finding(WARNING,
                                    f"Region {reference}: outline crosses itself, so its "
                                    f"area is ambiguous", image_path, reference))

    for index, first in enumerate(document.annotations):
        for second in document.annotations[index + 1:]:
            if len(first.points) < 3 or len(second.points) < 3:
                continue
            if geometry.polygons_overlap(first.points, second.points):
                findings.append(Finding(WARNING,
                                        f"Regions {first.id} and {second.id} overlap",
                                        image_path, first.id))

    findings.sort(key=lambda finding: 0 if finding.is_error else 1)
    return findings


def validate_set(items):
    """Findings across a working set of (image_path, document) pairs."""
    findings = []
    for image_path, document in items:
        if document is None:
            continue
        if not document.annotations:
            findings.append(Finding(WARNING, "No regions annotated", image_path, None))
            continue
        findings.extend(validate_document(document, image_path))
    findings.sort(key=lambda finding: 0 if finding.is_error else 1)
    return findings


def summarise(findings):
    errors = sum(1 for finding in findings if finding.is_error)
    return errors, len(findings) - errors
