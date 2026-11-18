##############################################################################################
# Purpose: Polygon maths, in plain Python and numpy, with no user interface and no Pillow.
#
# Coordinates everywhere in this module are (x, y) pairs in image pixel space. A polygon is a
# closed ring given as a list of points with the closing edge implied - the first point is
# never repeated at the end.
##############################################################################################

import math

import numpy as np


def polygon_area(points):
    """Shoelace area in square pixels.

    Deliberately the same formula as PolygonUtils.calculate_polygon_area in the detector, so
    an area measured here and an area measured there agree to the last decimal.
    """
    if points is None or len(points) < 3:
        return 0.0
    coordinates = np.asarray(points, dtype=np.float64)
    x, y = coordinates[:, 0], coordinates[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def bounding_box(points):
    """(min_x, min_y, max_x, max_y), or None for an empty ring."""
    if not points:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def centroid(points):
    """Area-weighted centroid, falling back to the mean of the vertices for a degenerate ring."""
    if not points:
        return 0.0, 0.0
    coordinates = np.asarray(points, dtype=np.float64)
    x, y = coordinates[:, 0], coordinates[:, 1]
    next_x, next_y = np.roll(x, -1), np.roll(y, -1)
    cross = x * next_y - next_x * y
    double_area = float(cross.sum())
    if abs(double_area) < 1e-9:
        return float(x.mean()), float(y.mean())
    cx = float(((x + next_x) * cross).sum() / (3.0 * double_area))
    cy = float(((y + next_y) * cross).sum() / (3.0 * double_area))
    return cx, cy


def point_in_polygon(point, points):
    """Ray casting. Points exactly on an edge may fall either way, which is fine for picking."""
    if not points or len(points) < 3:
        return False
    x, y = float(point[0]), float(point[1])
    inside = False
    count = len(points)
    j = count - 1
    for i in range(count):
        xi, yi = float(points[i][0]), float(points[i][1])
        xj, yj = float(points[j][0]), float(points[j][1])
        if (yi > y) != (yj > y):
            crossing_x = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < crossing_x:
                inside = not inside
        j = i
    return inside


def distance_to_segment(point, start, end):
    """Shortest distance from a point to a line segment."""
    px, py = float(point[0]), float(point[1])
    ax, ay = float(start[0]), float(start[1])
    bx, by = float(end[0]), float(end[1])
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def nearest_edge(point, points):
    """(index, distance) of the closest edge, where index i is the edge from i to i+1."""
    if not points or len(points) < 2:
        return -1, float("inf")
    best_index, best_distance = -1, float("inf")
    count = len(points)
    for i in range(count):
        distance = distance_to_segment(point, points[i], points[(i + 1) % count])
        if distance < best_distance:
            best_index, best_distance = i, distance
    return best_index, best_distance


def nearest_vertex(point, points):
    """(index, distance) of the closest vertex."""
    if not points:
        return -1, float("inf")
    best_index, best_distance = -1, float("inf")
    for i, vertex in enumerate(points):
        distance = math.hypot(float(point[0]) - float(vertex[0]),
                              float(point[1]) - float(vertex[1]))
        if distance < best_distance:
            best_index, best_distance = i, distance
    return best_index, best_distance


def drop_duplicate_points(points, tolerance=1e-6):
    """Remove consecutive duplicates, including the wrap-around pair."""
    if not points:
        return []
    cleaned = [tuple(float(v) for v in points[0])]
    for point in points[1:]:
        x, y = float(point[0]), float(point[1])
        if math.hypot(x - cleaned[-1][0], y - cleaned[-1][1]) > tolerance:
            cleaned.append((x, y))
    while len(cleaned) > 1 and math.hypot(cleaned[0][0] - cleaned[-1][0],
                                          cleaned[0][1] - cleaned[-1][1]) <= tolerance:
        cleaned.pop()
    return cleaned


def simplify(points, tolerance):
    """Ramer-Douglas-Peucker over a closed ring.

    The ring is cut open by repeating the first point at the end, simplified as a path, and
    closed again. Cutting at an arbitrary point pins that one vertex, which on a ring of
    dozens of points is not worth a more elaborate scheme.
    """
    if tolerance <= 0 or len(points) < 4:
        return list(points)
    opened = list(points) + [points[0]]
    result = _rdp(opened, float(tolerance))
    if len(result) > 1 and result[0] == result[-1]:
        result = result[:-1]
    return result if len(result) >= 3 else list(points)


def _rdp(points, tolerance):
    if len(points) < 3:
        return list(points)
    start = np.asarray(points[0], dtype=np.float64)
    end = np.asarray(points[-1], dtype=np.float64)
    segment = end - start
    length = float(math.hypot(segment[0], segment[1]))

    interior = np.asarray(points[1:-1], dtype=np.float64)
    if length == 0.0:
        distances = np.hypot(interior[:, 0] - start[0], interior[:, 1] - start[1])
    else:
        distances = np.abs(
            segment[0] * (start[1] - interior[:, 1]) - segment[1] * (start[0] - interior[:, 0])
        ) / length

    farthest = int(np.argmax(distances))
    if float(distances[farthest]) <= tolerance:
        return [points[0], points[-1]]

    split = farthest + 1
    left = _rdp(points[:split + 1], tolerance)
    right = _rdp(points[split:], tolerance)
    return left[:-1] + right


def translate(points, dx, dy):
    return [(float(x) + dx, float(y) + dy) for x, y in points]


def clamp_to_image(points, width, height):
    return [(min(max(float(x), 0.0), float(width)),
             min(max(float(y), 0.0), float(height))) for x, y in points]


def boxes_overlap(first, second):
    """Do two (min_x, min_y, max_x, max_y) boxes intersect?"""
    if first is None or second is None:
        return False
    return not (first[2] < second[0] or second[2] < first[0] or
                first[3] < second[1] or second[3] < first[1])


def polygons_overlap(first, second):
    """Approximate overlap test: bounding boxes, then vertex containment both ways.

    This misses the case of two rings that cross without either holding a vertex of the
    other, which for hand-drawn regions is rare enough that paying for exact intersection is
    not worth it. Used only to raise a validation warning, never to change geometry.
    """
    box_first, box_second = bounding_box(first), bounding_box(second)
    if not boxes_overlap(box_first, box_second):
        return False
    if any(point_in_polygon(point, second) for point in first):
        return True
    return any(point_in_polygon(point, first) for point in second)


def segments_properly_intersect(a1, a2, b1, b2):
    """True when two segments cross, ignoring shared endpoints and collinear touching."""

    def orientation(p, q, r):
        value = ((float(q[1]) - float(p[1])) * (float(r[0]) - float(q[0])) -
                 (float(q[0]) - float(p[0])) * (float(r[1]) - float(q[1])))
        if abs(value) < 1e-12:
            return 0
        return 1 if value > 0 else 2

    o1 = orientation(a1, a2, b1)
    o2 = orientation(a1, a2, b2)
    o3 = orientation(b1, b2, a1)
    o4 = orientation(b1, b2, a2)
    return o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4)


def is_self_intersecting(points):
    """Does the ring cross itself?

    O(n^2) over the edges, and called only during validation on rings of at most a few
    hundred points, so the quadratic cost is irrelevant next to the clarity.
    """
    count = len(points)
    if count < 4:
        return False
    for i in range(count):
        a1, a2 = points[i], points[(i + 1) % count]
        for j in range(i + 1, count):
            if j == i or (j + 1) % count == i or (i + 1) % count == j:
                continue
            b1, b2 = points[j], points[(j + 1) % count]
            if segments_properly_intersect(a1, a2, b1, b2):
                return True
    return False
