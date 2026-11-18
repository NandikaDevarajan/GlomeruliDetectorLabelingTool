##############################################################################################
# Purpose: One class per annotation tool, each a small state machine over mouse gestures.
#
# Tools never touch the window, the panels or the files. They are given a context by the
# application - the canvas, the document, the undo history, the active class - and they report
# back through it. That keeps every tool independent of the rest of the interface, and keeps
# the rules about undo in one place:
#
#   * context.begin_change() is called BEFORE the first mutation of a gesture, never after,
#     and never twice in one gesture.
#   * context.after_change() is called once the gesture has finished changing things.
#
# Every tool, whatever it draws with, produces a closed polygon. A region painted with the
# brush can be vertex-edited afterwards, and a region drawn with the polygon tool can be
# painted over.
##############################################################################################

import math

from . import geometry, raster
from .config import (CLOSE_POLYGON_RADIUS, FREEHAND_MIN_SCREEN_STEP,
                     FREEHAND_SIMPLIFY_TOLERANCE, MASK_MIN_COMPONENT_PIXELS,
                     VERTEX_HIT_RADIUS)


class Tool:
    """Base class. Every handler is optional; the default is to do nothing."""

    name = "tool"
    label = "Tool"
    cursor = "crosshair"
    wants_handles = False

    def __init__(self, context):
        self.context = context
        self._pushed = False

    # ------------------------------------------------------------------ helpers

    @property
    def document(self):
        return self.context.document

    def begin_change(self):
        """Snapshot for undo, at most once per gesture."""
        if not self._pushed:
            self.context.begin_change()
            self._pushed = True

    def finish(self):
        changed = self._pushed
        self._pushed = False
        if changed:
            self.context.after_change()
        return changed

    def screen_distance(self, a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1]) * self.context.canvas.zoom

    # ------------------------------------------------------------------- events

    def activate(self):
        pass

    def deactivate(self):
        self.cancel()

    def cancel(self):
        """Abandon whatever is in progress. Must leave the document untouched."""
        self.context.canvas.set_preview(None)
        self._pushed = False

    def on_press(self, point, event):
        pass

    def on_drag(self, point, event):
        pass

    def on_release(self, point, event):
        pass

    def on_motion(self, point, event):
        pass

    def on_right_click(self, point, event):
        pass

    def on_double_click(self, point, event):
        pass

    def on_key(self, keysym):
        return False


class SelectTool(Tool):
    name = "select"
    label = "Select"
    cursor = "arrow"

    def __init__(self, context):
        super().__init__(context)
        self._moving = None
        self._origin = None
        self._start_points = None

    def on_press(self, point, event):
        if self.document is None:
            return
        annotation = self.document.pick(point)
        self.context.select(annotation.id if annotation else None)
        if annotation is not None:
            self._moving = annotation.id
            self._origin = point
            self._start_points = list(annotation.points)

    def on_drag(self, point, event):
        if self._moving is None:
            return
        annotation = self.document.get(self._moving)
        if annotation is None:
            return
        # The snapshot is taken here, not on press, so a click that selects without dragging
        # does not land an empty step on the undo stack.
        self.begin_change()
        dx = point[0] - self._origin[0]
        dy = point[1] - self._origin[1]
        annotation.points = geometry.translate(self._start_points, dx, dy)
        self.context.canvas.repaint()

    def on_release(self, point, event):
        self._moving = None
        self._origin = None
        self._start_points = None
        self.finish()

    def on_double_click(self, point, event):
        if self.document is None:
            return
        annotation = self.document.pick(point)
        if annotation is not None:
            self.context.select(annotation.id)


class PolygonTool(Tool):
    name = "polygon"
    label = "Polygon"

    def __init__(self, context):
        super().__init__(context)
        self.points = []
        self._cursor = None

    def cancel(self):
        self.points = []
        self._cursor = None
        super().cancel()

    def _refresh(self):
        self.context.canvas.set_preview({
            "kind": "polygon",
            "points": list(self.points),
            "cursor": self._cursor,
            "color": self.context.active_color(),
        })

    def on_press(self, point, event):
        if self.document is None:
            return
        if self.points and self.screen_distance(point, self.points[0]) <= CLOSE_POLYGON_RADIUS:
            self.commit()
            return
        self.points.append(point)
        self._refresh()
        self.context.status(f"{len(self.points)} points - double-click or Enter to close, "
                            f"Escape to abandon")

    def on_motion(self, point, event):
        if self.points:
            self._cursor = point
            self._refresh()

    def on_double_click(self, point, event):
        self.commit()

    def on_right_click(self, point, event):
        self.commit()

    def on_key(self, keysym):
        if keysym in ("Return", "KP_Enter"):
            self.commit()
            return True
        if keysym == "BackSpace":
            if self.points:
                self.points.pop()
                self._refresh()
            return True
        if keysym == "Escape":
            self.cancel()
            self.context.status("Polygon abandoned")
            return True
        return False

    def commit(self):
        points = geometry.drop_duplicate_points(self.points)
        self.points = []
        self._cursor = None
        self.context.canvas.set_preview(None)
        if len(points) < 3:
            self.context.status("A region needs at least three points")
            return
        self.begin_change()
        annotation = self.document.add(self.context.active_class_id, points)
        self.context.select(annotation.id)
        self.finish()


class FreehandTool(Tool):
    name = "freehand"
    label = "Freehand"

    def __init__(self, context):
        super().__init__(context)
        self.points = []

    def cancel(self):
        self.points = []
        super().cancel()

    def on_press(self, point, event):
        if self.document is None:
            return
        self.points = [point]

    def on_drag(self, point, event):
        if not self.points:
            return
        # Record a point only after the cursor has travelled far enough on screen, so a slow
        # hand produces the same path as a quick one instead of thousands of coincident points.
        if self.screen_distance(point, self.points[-1]) >= FREEHAND_MIN_SCREEN_STEP:
            self.points.append(point)
            self.context.canvas.set_preview({
                "kind": "path",
                "points": list(self.points),
                "color": self.context.active_color(),
            })

    def on_release(self, point, event):
        points = self.points
        self.points = []
        self.context.canvas.set_preview(None)
        if self.document is None or len(points) < 3:
            return
        points = geometry.drop_duplicate_points(points)
        points = geometry.simplify(points, FREEHAND_SIMPLIFY_TOLERANCE)
        if len(points) < 3 or geometry.polygon_area(points) <= 0:
            self.context.status("Region too small to keep")
            return
        self.begin_change()
        annotation = self.document.add(self.context.active_class_id, points)
        self.context.select(annotation.id)
        self.finish()
        self.context.status(f"Region {annotation.id}: {len(points)} points, "
                            f"{annotation.area_pixels:,.0f} px")

    def on_key(self, keysym):
        if keysym == "Escape" and self.points:
            self.cancel()
            return True
        return False


class RectangleTool(Tool):
    name = "rectangle"
    label = "Rectangle"

    def __init__(self, context):
        super().__init__(context)
        self._anchor = None

    def cancel(self):
        self._anchor = None
        super().cancel()

    @staticmethod
    def _corners(anchor, point):
        x0, y0 = anchor
        x1, y1 = point
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def on_press(self, point, event):
        if self.document is not None:
            self._anchor = point

    def on_drag(self, point, event):
        if self._anchor is None:
            return
        self.context.canvas.set_preview({
            "kind": "rect",
            "points": self._corners(self._anchor, point),
            "color": self.context.active_color(),
        })

    def on_release(self, point, event):
        anchor = self._anchor
        self._anchor = None
        self.context.canvas.set_preview(None)
        if anchor is None:
            return
        points = self._corners(anchor, point)
        if geometry.polygon_area(points) < 4:
            self.context.status("Rectangle too small to keep")
            return
        self.begin_change()
        annotation = self.document.add(self.context.active_class_id, points)
        self.context.select(annotation.id)
        self.finish()


class VertexTool(Tool):
    name = "vertex"
    label = "Edit vertices"
    wants_handles = True

    def __init__(self, context):
        super().__init__(context)
        self._dragging = None

    def on_press(self, point, event):
        if self.document is None:
            return
        annotation = self.document.get(self.context.selected_id)

        if annotation is not None:
            index = self.context.canvas.hit_vertex(point, annotation, VERTEX_HIT_RADIUS)
            if index >= 0:
                self._dragging = index
                return
            # Clicking an edge inserts a vertex there and starts dragging it, so adding a
            # point and placing it is one gesture rather than two.
            edge = self.context.canvas.hit_edge(point, annotation, VERTEX_HIT_RADIUS)
            if edge >= 0:
                self.begin_change()
                annotation.points.insert(edge + 1, point)
                self._dragging = edge + 1
                self.context.canvas.repaint()
                return

        picked = self.document.pick(point)
        self.context.select(picked.id if picked else None)

    def on_drag(self, point, event):
        if self._dragging is None:
            return
        annotation = self.document.get(self.context.selected_id)
        if annotation is None or self._dragging >= len(annotation.points):
            return
        self.begin_change()
        annotation.points[self._dragging] = point
        self.context.canvas.repaint()

    def on_release(self, point, event):
        self._dragging = None
        self.finish()

    def on_right_click(self, point, event):
        annotation = self.document.get(self.context.selected_id) if self.document else None
        if annotation is None:
            return
        index = self.context.canvas.hit_vertex(point, annotation, VERTEX_HIT_RADIUS)
        if index < 0:
            return
        if len(annotation.points) <= 3:
            self.context.status("A region cannot have fewer than three vertices")
            return
        self.begin_change()
        del annotation.points[index]
        self.finish()


class _MaskTool(Tool):
    """Shared machinery for the brush and the eraser.

    Both rasterise the region they are changing, stamp a disc along the drag, and trace the
    result back to polygons once the button comes up. Tracing on every mouse move would be
    far too slow, so what the user sees during the stroke is a thick round-capped line of the
    brush diameter, which is the same shape the mask is taking.
    """

    adding = True

    def __init__(self, context):
        super().__init__(context)
        self._mask = None
        self._target_id = None
        self._last = None
        self._stroke = []

    def cancel(self):
        self._mask = None
        self._target_id = None
        self._last = None
        self._stroke = []
        super().cancel()

    def _start_mask(self, point):
        raise NotImplementedError

    def on_press(self, point, event):
        if self.document is None:
            return
        if not self._start_mask(point):
            return
        self._last = point
        self._stroke = [point]
        radius = self.context.brush_radius
        raster.stamp_disc(self._mask, point[0], point[1], radius, self.adding)
        self._refresh_preview()

    def on_drag(self, point, event):
        if self._mask is None:
            return
        radius = self.context.brush_radius
        raster.stamp_segment(self._mask, self._last[0], self._last[1],
                             point[0], point[1], radius, self.adding)
        self._last = point
        self._stroke.append(point)
        self._refresh_preview()
        self.context.canvas.set_brush_cursor((point[0], point[1], radius))

    def _refresh_preview(self):
        self.context.canvas.set_preview({
            "kind": "stroke",
            "points": list(self._stroke) if len(self._stroke) > 1 else
                      [self._stroke[0], self._stroke[0]],
            "radius": self.context.brush_radius,
            "color": self.context.active_color() if self.adding else "#000000",
        })

    def on_motion(self, point, event):
        self.context.canvas.set_brush_cursor((point[0], point[1], self.context.brush_radius))

    def on_release(self, point, event):
        mask = self._mask
        target_id = self._target_id
        self._mask = None
        self._target_id = None
        self._last = None
        self._stroke = []
        self.context.canvas.set_preview(None)
        if mask is None:
            return
        self._apply(mask, target_id)

    def _apply(self, mask, target_id):
        polygons = raster.mask_to_polygons(mask, min_pixels=MASK_MIN_COMPONENT_PIXELS)
        self.begin_change()

        if not polygons:
            if target_id is not None:
                self.document.remove(target_id)
                self.context.select(None)
            self.finish()
            return

        class_id = self.context.active_class_id
        if target_id is not None:
            existing = self.document.get(target_id)
            if existing is not None:
                class_id = existing.class_id
                # The largest piece keeps the identity, so an id in an export does not move
                # around because the user tidied an edge.
                existing.points = polygons[0]
            else:
                target_id = None

        if target_id is None:
            first = self.document.add(class_id, polygons[0])
            target_id = first.id

        # A stroke that separates a region into pieces leaves each piece as its own region.
        for extra in polygons[1:]:
            self.document.add(class_id, extra)

        self.context.select(target_id)
        self.finish()
        if len(polygons) > 1:
            self.context.status(f"Region split into {len(polygons)} regions")


class BrushTool(_MaskTool):
    name = "brush"
    label = "Brush"
    adding = True

    def _start_mask(self, point):
        selected = self.document.get(self.context.selected_id)
        if selected is None:
            # Painting with nothing selected starts a new region rather than refusing.
            self._mask = raster.polygon_to_mask([], self.document.width, self.document.height)
            self._target_id = None
        else:
            self._mask = raster.polygon_to_mask(selected.points,
                                                self.document.width, self.document.height)
            self._target_id = selected.id
        return True


class EraserTool(_MaskTool):
    name = "eraser"
    label = "Eraser"
    adding = False

    def _start_mask(self, point):
        target = self.document.get(self.context.selected_id)
        if target is None:
            target = self.document.pick(point)
        if target is None:
            self.context.status("Select a region first, or start the stroke inside one")
            return False
        self._mask = raster.polygon_to_mask(target.points,
                                            self.document.width, self.document.height)
        self._target_id = target.id
        self.context.select(target.id)
        return True


TOOL_CLASSES = [SelectTool, PolygonTool, FreehandTool, RectangleTool,
                BrushTool, EraserTool, VertexTool]

# Single-key shortcuts. The drawing hand stays on the mouse, so the other hand needs the
# tools within reach without a modifier.
TOOL_KEYS = {
    "v": "select", "p": "polygon", "f": "freehand", "r": "rectangle",
    "b": "brush", "e": "eraser", "n": "vertex",
}
