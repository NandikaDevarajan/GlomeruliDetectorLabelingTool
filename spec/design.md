# Histology Labeler - Design

## 1. Window layout

```
+----------------------------------------------------------------------------------+
| File   Edit   View   Classes   Export   Help                                      |
+----------------------------------------------------------------------------------+
| [Sel][Poly][Free][Rect][Brush][Eras][Vert] | Brush -[==]+ | [<] 7/56 [>] | [Fit][1:1]|
+-------------------------------------------------------+--------------------------+
|                                                        |  CLASSES                 |
|                                                        |  [#] Glomerulus      12  |
|                                                        |  [#] Sclerotic Glom.  3  |
|                                                        |  [#] Partial Glom.    0  |
|                   image canvas                         |  [#] Other Region     1  |
|              (scroll = zoom at cursor,                 |  [ New ][Edit][Delete]   |
|               middle drag or space drag = pan)         +--------------------------+
|                                                        |  REGIONS                 |
|                                                        |  o 1  Glomerulus   8420  |
|                                                        |  o 2  Glomerulus   7765  |
|                                                        |  * 3  Sclerotic    6110  |
|                                                        |  [Hide][Delete][Class v] |
|                                                        +--------------------------+
|                                                        |  DISPLAY                 |
|                                                        |  Opacity [=====----]     |
|                                                        |  [x] Fills  [x] Outlines |
|                                                        |  [x] Labels              |
+--------------------------------------------------------+--------------------------+
| 71121_1.tif   2560 x 1920   0.850 um/px   zoom 38%   region 3: 6110 px / 4415 um2 |
+----------------------------------------------------------------------------------+
```

The right-hand column is fixed width and scrolls internally. The canvas takes everything
else. The status bar is one line and never wraps.

A left-hand file list was considered and rejected: a folder of 56 images needs navigation,
not a permanent panel, and the counter plus prev/next in the toolbar does that in a fraction
of the space. The full set is available from the Image menu, with annotation counts.

## 2. Interaction

### 2.1 Mouse

| Gesture | Effect |
|---|---|
| Wheel | Zoom about the cursor, 1.15x per notch, clamped to 2% - 3200% |
| Middle drag | Pan |
| Space + left drag | Pan, for mice without a usable middle button |
| Left press/drag/release | Whatever the active tool does |
| Right click | Context-dependent: closes a polygon, deletes a vertex, opens the region menu |
| Double click | Closes a polygon in progress, or selects the region under the cursor |

Zoom about the cursor means the image point under the pointer stays under the pointer. That
is the difference between zooming in on a glomerulus and hunting for it afterwards.

### 2.2 Keyboard

| Key | Action |
|---|---|
| `V` `P` `F` `R` `B` `E` `N` | Select, Polygon, Freehand, Rectangle, Brush, Eraser, Vertices |
| `Ctrl+Z` / `Ctrl+Y`, `Ctrl+Shift+Z` | Undo / redo |
| `Ctrl+S` | Save now |
| `Ctrl+O` / `Ctrl+Shift+O` | Open file / open folder |
| `Page Down` `Page Up`, or `A` `D` | Previous / next image |
| `Delete` | Delete selection |
| `Escape` | Abandon the gesture in progress, else clear the selection |
| `Enter` | Close the polygon in progress |
| `Backspace` | Remove the last placed vertex |
| `[` `]` | Brush smaller / larger |
| `Ctrl+0` / `Ctrl+1` | Zoom to fit / 100 percent |
| `H` | Hide or show the selected region |
| `Tab` | Select the next region |

Single letters are tool switches because the hand that draws stays on the mouse and the
other hand sits on the left of the keyboard. Annotation is repetitive; every modifier saved
is paid back a few hundred times.

### 2.3 Cursors

Crosshair for the drawing tools, arrow for select, a circle sized to the brush for brush and
eraser, a fleur while panning. The brush cursor is drawn on the canvas rather than set as a
window cursor, because its size must track the zoom.

## 3. Drawing tools in detail

### 3.1 Polygon

Click places a vertex. A rubber-band line follows the cursor from the last vertex. The first
vertex is drawn as a slightly larger handle; clicking within 10 screen pixels of it closes
the region, as does double-click, Enter, or right-click. Fewer than three vertices at
closing time abandons the region rather than storing a degenerate one.

### 3.2 Freehand

Points are appended while the button is held, but only when the cursor has moved at least
2 screen pixels since the last appended point. That bounds the raw path at roughly one point
per 2 pixels of travel regardless of how slowly the hand moves.

On release the path is closed, then simplified with Ramer-Douglas-Peucker at a tolerance of
1 image pixel. A traced glomerulus comes out at 40 to 120 vertices, which is accurate to
well within the width of the line the user drew, and is editable afterwards without a
thousand handles in the way.

### 3.3 Rectangle

Press, drag, release. Stored as four vertices, so the vertex editor can subsequently pull it
out of square - it is a starting shape, not a locked type.

### 3.4 Brush and eraser

Both operate on a boolean mask at full image resolution:

1. Rasterise the target region into a mask (or start from an empty mask for a new region).
2. For each mouse move, stamp a filled circle of the current radius, interpolating along the
   segment from the previous position so a fast drag does not leave gaps.
3. On release, trace the mask back to polygons.

The stamp is a precomputed boolean disc, placed with array slicing. A radius-40 stamp on a
2560 x 1920 mask takes well under a millisecond, so the live feedback is the canvas preview,
not the mask.

Tracing uses `MaskPostProcessor.label_components`, `fill_holes` and `trace_outer_contour`.
The brush keeps the largest resulting component. The eraser keeps every component above 50
pixels, which is how a region split in two becomes two regions (FR-15).

Preview during the stroke is a stroked polyline on the canvas with width equal to the brush
diameter in screen pixels and round joins, which looks exactly like what the mask will be.

### 3.5 Vertex editing

Handles are 5-pixel squares at each vertex, hollow circles at edge midpoints. Dragging a
handle moves the vertex. Clicking a midpoint inserts a real vertex there and begins dragging
it, so adding and placing a vertex is one gesture. Right-clicking a handle deletes it unless
only three remain.

Hit radius is 7 screen pixels, which at any zoom is a comfortable target and small enough not
to swallow neighbouring handles on a dense contour.

## 4. Sidecar format

`71121_1.tif` beside `71121_1.json`:

```json
{
  "format": "histology-labeler",
  "version": 1,
  "created": "2026-10-30T09:14:22",
  "modified": "2026-10-30T10:02:51",
  "image": {
    "file": "71121_1.tif",
    "width": 2560,
    "height": 1920,
    "pixel_size_um": 0.85
  },
  "classes": [
    { "id": 1, "name": "Glomerulus", "color": "#E6194B" },
    { "id": 2, "name": "Sclerotic Glomerulus", "color": "#3CB44B" }
  ],
  "annotations": [
    {
      "id": 1,
      "class_id": 1,
      "class_name": "Glomerulus",
      "points": [[1204.5, 882.0], [1210.2, 901.7], [1198.0, 915.5]],
      "area_pixels": 8419.75,
      "visible": true,
      "notes": ""
    }
  ]
}
```

Notes on the choices:

- `format` is the guard from FR-43. Nothing without it is ever overwritten.
- `classes` is embedded even though the class table also lives in the application settings.
  A sidecar that travels to another machine is then still self-describing, and an id can
  always be resolved to a name and a colour.
- `class_name` is denormalised alongside `class_id` for the benefit of anything reading the
  file without resolving the class table. The id is authoritative on load.
- `area_pixels` is derived and recomputed on load. It is written because a person reading
  the file, or a script tallying areas, should not have to implement the shoelace formula.
- `points` is a closed ring, with the closing edge implied. The first point is not repeated.
- Image dimensions are present so coordinates can be normalised, and so a changed image can
  be detected (FR-42).

## 5. Export formats

All exports write into a folder the user chooses, and overwrite only files they created.

### COCO (`annotations.json`)

Standard instance segmentation. `segmentation` is `[[x1,y1,x2,y2,...]]` in absolute pixels,
`bbox` is `[x,y,w,h]`, `area` is the shoelace area, `iscrowd` is 0. Categories come from the
class table, with the class id as the category id.

### YOLO segmentation

`labels/<stem>.txt`, one line per region: `class_index x1 y1 x2 y2 ...` with every coordinate
divided by the image dimension and clamped to 0..1. `classes.txt` lists class names in index
order, and `data.yaml` records the same for the Ultralytics loader. The class index is the
position in the class table, not the class id, because YOLO requires indices to be dense from
zero.

### Binary masks

`masks/<stem>/region_<id>_<class>.png` per region, and `masks/<stem>/class_<class>.png` as
the union per class. White on black, same dimensions as the image.

### Project bundle

One JSON holding every sidecar in the working set, under the relative image paths, so a whole
job is one file to archive or hand over.

### Training pair

```
Data/<name>.tif     byte-for-byte copy of the clean image
Train/<name>.tif    the same image with every region outlined in pure red
```

The outline is drawn with `ImageDraw.polygon(outline="red")` and the area is written in
yellow, which is exactly what `polygondrawer.py` produces. `ModelTrainer/prepare_dataset.py`
recovers masks by diffing `Train` against `Data` and keeping red-dominant changed pixels, so
an export of this shape is trainable with no change to the pipeline. The yellow text is
below the size filters in that script and is ignored, as it already is for the model's own
drawings.

This is the format that closes the loop: label a new stain here, export a training pair, and
retrain.

## 6. Validation rules

| Check | Severity | Reason |
|---|---|---|
| Fewer than 3 distinct points | error | Not a region; most consumers will crash |
| Zero or near-zero area | error | A collapsed ring, usually an accidental click-drag |
| Non-finite coordinate | error | Corrupt; would poison a whole training run silently |
| Entirely outside the image | error | Certainly a mistake |
| Partly outside the image | warning | Legitimate for a glomerulus cut by the edge |
| Duplicate region id | error | Breaks every export format |
| Overlapping regions | warning | Legitimate when touching; often a double-draw |
| Self-intersecting ring | warning | Area is ill-defined; usually a freehand crossing |
| Image with no regions | warning | Often intended - a field with no glomeruli is data too |

Partly-outside is a warning rather than an error on purpose. A glomerulus running off the
edge of a field is normal, and the existing pipeline already handles border-cut outlines; an
error there would train the user to click past the dialog.

Findings are listed in a dialog with image, region and message. Selecting one opens that
image and selects that region, so a finding is a short walk from a fix (FR-55).

## 7. Performance

| Operation | Budget | How |
|---|---|---|
| Open a 2560x1920 TIFF | < 2 s | Pillow, first frame only, no full-size conversion |
| Repaint at any zoom | < 30 ms | Crop then resize: work scales with viewport, not image |
| Freehand point | < 2 ms | Append and extend one canvas item; no recomposite |
| Brush stamp | < 1 ms | Precomputed disc, numpy slice assignment |
| Mask to polygon on release | < 150 ms | Run-length union-find; once per stroke, not per move |
| Undo snapshot | < 5 ms | Deep copy of coordinates only |

The repaint budget is the one that matters. Resampling uses bilinear when zoomed out, where
it suppresses aliasing on fine tissue texture, and nearest when zoomed past 1:1, where a
pathologist wants to see the actual pixel grid rather than a smoothed guess at it.

## 8. Settings

`LabelingTool/settings.json`, written on exit:

```json
{
  "classes": [ ... ],
  "active_class_id": 1,
  "brush_radius": 20,
  "overlay_opacity": 0.35,
  "show_fills": true,
  "show_outlines": true,
  "show_labels": true,
  "last_folder": "C:\\Claude\\GloumerliDetector\\NewImages",
  "window": "1400x900"
}
```

Missing or unreadable settings fall back to defaults without complaint; this file is a
convenience, never a requirement.
