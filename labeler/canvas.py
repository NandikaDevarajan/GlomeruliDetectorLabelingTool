##############################################################################################
# Purpose: The image canvas - the view transform, the drawing, and turning screen positions
# back into image coordinates.
#
# Rendering is in two layers, because the tkinter canvas cannot blend colours (see
# spec/architecture.md, 3.3):
#
#   base     the visible part of the image, with the filled regions alpha-composited onto it
#            by Pillow and handed over as a single PhotoImage
#   vectors  outlines, vertex handles, labels, the brush cursor and the gesture in progress,
#            as ordinary canvas items, which stay crisp at any zoom and are cheap to redraw
#
# The base layer is rebuilt only when the image, the view or the regions change. A gesture in
# progress redraws the vector layer alone, which is what keeps freehand drawing smooth.
#
# No stored coordinate ever depends on the view: zoom and pan live here and nowhere else.
##############################################################################################

import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

from . import geometry
from .config import MAX_ZOOM, MIN_ZOOM, VERTEX_HANDLE_SIZE

BACKGROUND = "#2b2b2b"
SELECTED_OUTLINE_WIDTH = 3
NORMAL_OUTLINE_WIDTH = 2
HANDLE_FILL = "#FFFFFF"
HANDLE_OUTLINE = "#000000"
MIDPOINT_FILL = "#FFD966"


class ImageCanvas(tk.Canvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, background=BACKGROUND, highlightthickness=0, **kwargs)

        self.image = None
        self.image_width = 0
        self.image_height = 0

        self.document = None
        self.class_table = None

        # View: zoom, and the image coordinate sitting at screen (0, 0).
        self.zoom = 1.0
        self.origin_x = 0.0
        self.origin_y = 0.0

        self.selected_id = None
        self.show_fills = True
        self.show_outlines = True
        self.show_labels = True
        self.overlay_opacity = 0.35
        self.show_handles = False

        # The gesture in progress, owned by the active tool. See set_preview.
        self.preview = None
        self.brush_cursor = None

        self._photo = None
        self._base_item = None
        self._vector_items = []

        self.bind("<Configure>", lambda event: self.repaint())

    # ------------------------------------------------------------ view transform

    def to_screen(self, x, y):
        return ((float(x) - self.origin_x) * self.zoom,
                (float(y) - self.origin_y) * self.zoom)

    def to_image(self, x, y):
        return (float(x) / self.zoom + self.origin_x,
                float(y) / self.zoom + self.origin_y)

    def viewport(self):
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        return width, height

    def set_image(self, loaded_image):
        self.image = loaded_image.image if loaded_image else None
        self.image_width = loaded_image.width if loaded_image else 0
        self.image_height = loaded_image.height if loaded_image else 0
        self.selected_id = None
        self.preview = None

    def zoom_to_fit(self):
        if not self.image_width or not self.image_height:
            return
        width, height = self.viewport()
        scale = min(width / self.image_width, height / self.image_height)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, scale))
        # Centre whatever margin is left over, so a portrait image is not pinned to the left.
        self.origin_x = (self.image_width - width / self.zoom) / 2.0
        self.origin_y = (self.image_height - height / self.zoom) / 2.0
        self.repaint()

    def zoom_to_actual(self):
        self.zoom_at(1.0, *[v / 2 for v in self.viewport()])

    def zoom_at(self, new_zoom, screen_x, screen_y):
        """Set the zoom while keeping the image point under (screen_x, screen_y) in place."""
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))
        if abs(new_zoom - self.zoom) < 1e-9:
            return
        anchor_x, anchor_y = self.to_image(screen_x, screen_y)
        self.zoom = new_zoom
        self.origin_x = anchor_x - screen_x / self.zoom
        self.origin_y = anchor_y - screen_y / self.zoom
        self.repaint()

    def zoom_by(self, factor, screen_x, screen_y):
        self.zoom_at(self.zoom * factor, screen_x, screen_y)

    def pan_by(self, screen_dx, screen_dy):
        self.origin_x -= screen_dx / self.zoom
        self.origin_y -= screen_dy / self.zoom
        self.repaint()

    def centre_on(self, x, y):
        width, height = self.viewport()
        self.origin_x = float(x) - width / (2.0 * self.zoom)
        self.origin_y = float(y) - height / (2.0 * self.zoom)
        self.repaint()

    def frame_box(self, box, margin=1.4):
        """Zoom and pan so a (min_x, min_y, max_x, max_y) box fills most of the view."""
        if not box:
            return
        width, height = self.viewport()
        box_width = max(1.0, box[2] - box[0]) * margin
        box_height = max(1.0, box[3] - box[1]) * margin
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM,
                                      min(width / box_width, height / box_height)))
        self.centre_on((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)

    # -------------------------------------------------------------------- state

    def set_preview(self, preview):
        """Describe the gesture in progress, or None.

        A dict with a 'kind' of 'path', 'polygon', 'rect' or 'stroke', its points in image
        coordinates, and a colour. Tools own this; the canvas only draws it.
        """
        self.preview = preview
        self.render_vectors()

    def set_brush_cursor(self, position_and_radius):
        self.brush_cursor = position_and_radius
        self.render_vectors()

    # ----------------------------------------------------------------- painting

    def repaint(self):
        self.render_base()
        self.render_vectors()

    def _class_color(self, class_id):
        entry = self.class_table.get(class_id) if self.class_table else None
        return entry.color if entry else "#E6194B"

    def _class_rgb(self, class_id):
        entry = self.class_table.get(class_id) if self.class_table else None
        return entry.rgb() if entry else (230, 25, 75)

    def render_base(self):
        """Visible crop of the image with the filled regions composited onto it."""
        if self._base_item is not None:
            self.delete(self._base_item)
            self._base_item = None
        if self.image is None:
            return

        width, height = self.viewport()
        canvas_image = Image.new("RGB", (width, height), BACKGROUND)

        # Resize straight from a float box: Pillow crops and scales in one pass, and the
        # work is proportional to the viewport rather than to the whole image.
        left = max(0.0, self.origin_x)
        top = max(0.0, self.origin_y)
        right = min(float(self.image_width), self.origin_x + width / self.zoom)
        bottom = min(float(self.image_height), self.origin_y + height / self.zoom)

        if right > left and bottom > top:
            target_width = max(1, int(round((right - left) * self.zoom)))
            target_height = max(1, int(round((bottom - top) * self.zoom)))
            # Zoomed out, bilinear suppresses aliasing on fine tissue texture. Zoomed in past
            # 1:1, nearest shows the real pixel grid instead of a smoothed guess at it.
            resample = Image.BILINEAR if self.zoom < 1.0 else Image.NEAREST
            piece = self.image.resize((target_width, target_height), resample,
                                      box=(left, top, right, bottom))
            canvas_image.paste(piece, (int(round((left - self.origin_x) * self.zoom)),
                                       int(round((top - self.origin_y) * self.zoom))))

        if self.show_fills and self.overlay_opacity > 0.01 and self.document is not None:
            canvas_image = self._composite_fills(canvas_image, width, height)

        self._photo = ImageTk.PhotoImage(canvas_image)
        self._base_item = self.create_image(0, 0, anchor="nw", image=self._photo)
        self.tag_lower(self._base_item)

    def _composite_fills(self, canvas_image, width, height):
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        alpha = int(round(max(0.0, min(1.0, self.overlay_opacity)) * 255))
        drew_any = False

        for annotation in self.document.annotations:
            if not annotation.visible or len(annotation.points) < 3:
                continue
            points = [self.to_screen(x, y) for x, y in annotation.points]
            if not self._intersects_viewport(points, width, height):
                continue
            red, green, blue = self._class_rgb(annotation.class_id)
            draw.polygon(points, fill=(red, green, blue, alpha))
            drew_any = True

        if not drew_any:
            return canvas_image
        return Image.alpha_composite(canvas_image.convert("RGBA"), overlay).convert("RGB")

    @staticmethod
    def _intersects_viewport(points, width, height):
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return not (max(xs) < 0 or min(xs) > width or max(ys) < 0 or min(ys) > height)

    def render_vectors(self):
        """Outlines, handles, labels, brush cursor and the gesture in progress."""
        for item in self._vector_items:
            self.delete(item)
        self._vector_items = []
        if self.image is None:
            return

        width, height = self.viewport()
        if self.document is not None and self.show_outlines:
            for annotation in self.document.annotations:
                self._draw_annotation(annotation, width, height)

        if self.document is not None and self.show_labels:
            for annotation in self.document.annotations:
                self._draw_label(annotation, width, height)

        if self.show_handles and self.selected_id is not None and self.document is not None:
            selected = self.document.get(self.selected_id)
            if selected is not None and selected.visible:
                self._draw_handles(selected)

        self._draw_preview()
        self._draw_brush_cursor()

    def _draw_annotation(self, annotation, width, height):
        if not annotation.visible or len(annotation.points) < 2:
            return
        points = [self.to_screen(x, y) for x, y in annotation.points]
        if not self._intersects_viewport(points, width, height):
            return
        selected = annotation.id == self.selected_id
        flat = []
        for point in points + [points[0]]:
            flat.extend(point)
        item = self.create_line(
            *flat,
            fill="#FFFFFF" if selected else self._class_color(annotation.class_id),
            width=SELECTED_OUTLINE_WIDTH if selected else NORMAL_OUTLINE_WIDTH,
            joinstyle="round",
        )
        self._vector_items.append(item)
        if selected:
            # A second line underneath in the class colour, so a white selection outline is
            # still readable over pale tissue and still says which class it belongs to.
            under = self.create_line(*flat, fill=self._class_color(annotation.class_id),
                                     width=SELECTED_OUTLINE_WIDTH + 2, joinstyle="round")
            self.tag_lower(under, item)
            self._vector_items.append(under)

    def _draw_label(self, annotation, width, height):
        if not annotation.visible or len(annotation.points) < 3:
            return
        box = annotation.bounding_box()
        screen_x, screen_y = self.to_screen(box[0], box[1])
        if screen_x < -200 or screen_y < -40 or screen_x > width or screen_y > height:
            return
        entry = self.class_table.get(annotation.class_id) if self.class_table else None
        text = f"{annotation.id}  {entry.name if entry else ''}"
        item = self.create_text(screen_x + 2, screen_y - 8, text=text, anchor="sw",
                                fill=self._class_color(annotation.class_id),
                                font=("Segoe UI", 8, "bold"))
        self._vector_items.append(item)

    def _draw_handles(self, annotation):
        size = VERTEX_HANDLE_SIZE
        points = annotation.points
        for index in range(len(points)):
            following = points[(index + 1) % len(points)]
            mid_x, mid_y = self.to_screen((points[index][0] + following[0]) / 2.0,
                                          (points[index][1] + following[1]) / 2.0)
            self._vector_items.append(self.create_oval(
                mid_x - size + 1, mid_y - size + 1, mid_x + size - 1, mid_y + size - 1,
                fill="", outline=MIDPOINT_FILL, width=2))
        for x, y in points:
            screen_x, screen_y = self.to_screen(x, y)
            self._vector_items.append(self.create_rectangle(
                screen_x - size, screen_y - size, screen_x + size, screen_y + size,
                fill=HANDLE_FILL, outline=HANDLE_OUTLINE))

    def _draw_preview(self):
        if not self.preview:
            return
        kind = self.preview.get("kind")
        points = self.preview.get("points") or []
        color = self.preview.get("color", "#FFD966")
        if not points:
            return
        screen = [self.to_screen(x, y) for x, y in points]

        if kind == "stroke":
            # The brush preview is a thick round-capped line, which is exactly the shape the
            # mask will take, so what is shown is what gets painted.
            if len(screen) >= 2:
                flat = [v for point in screen for v in point]
                diameter = max(2.0, self.preview.get("radius", 10) * 2 * self.zoom)
                self._vector_items.append(self.create_line(
                    *flat, fill=color, width=diameter, capstyle="round", joinstyle="round"))
            return

        closed = kind in ("path", "rect")
        flat = [v for point in screen for v in point]
        if closed and len(screen) >= 3:
            flat.extend(screen[0])
        if len(screen) >= 2:
            self._vector_items.append(self.create_line(
                *flat, fill=color, width=2, joinstyle="round",
                dash=() if kind != "polygon" else (6, 3)))

        if kind == "polygon":
            rubber = self.preview.get("cursor")
            if rubber is not None and screen:
                cursor = self.to_screen(*rubber)
                self._vector_items.append(self.create_line(
                    *screen[-1], *cursor, fill=color, width=1, dash=(3, 3)))
            for index, point in enumerate(screen):
                size = 5 if index == 0 else 3
                self._vector_items.append(self.create_oval(
                    point[0] - size, point[1] - size, point[0] + size, point[1] + size,
                    fill=color if index else "#FFFFFF", outline="#000000"))

    def _draw_brush_cursor(self):
        if not self.brush_cursor:
            return
        x, y, radius = self.brush_cursor
        screen_x, screen_y = self.to_screen(x, y)
        screen_radius = max(2.0, radius * self.zoom)
        self._vector_items.append(self.create_oval(
            screen_x - screen_radius, screen_y - screen_radius,
            screen_x + screen_radius, screen_y + screen_radius,
            outline="#FFFFFF", width=1))

    # ------------------------------------------------------------------ picking

    def hit_vertex(self, image_point, annotation, radius_screen):
        """Index of the vertex within the hit radius, or -1. Radius is in screen pixels."""
        if annotation is None:
            return -1
        index, distance = geometry.nearest_vertex(image_point, annotation.points)
        return index if distance * self.zoom <= radius_screen else -1

    def hit_edge(self, image_point, annotation, radius_screen):
        """Index of the edge within the hit radius, or -1."""
        if annotation is None:
            return -1
        index, distance = geometry.nearest_edge(image_point, annotation.points)
        return index if distance * self.zoom <= radius_screen else -1
