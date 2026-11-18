# Histology Labeler - Architecture

## 1. Shape of the thing

A single-process desktop application. No server, no database, no background workers, no
network. State lives in memory while an image is open and on disk as a JSON file beside each
image. Closing the application loses nothing that matters.

```
                       +--------------------------+
                       |        app.App           |   tkinter root, menus,
                       |   (controller + shell)   |   keyboard, orchestration
                       +--------------------------+
                         |        |            |
          +--------------+        |            +---------------+
          |                       |                            |
   +--------------+        +-------------+            +-----------------+
   | ImageCanvas  |<------>|  ToolHost   |            |   Side panels   |
   |  rendering   |        | active tool |            | classes, list,  |
   |  zoom / pan  |        | gestures    |            | display, status |
   +--------------+        +-------------+            +-----------------+
          |                       |                            |
          +-----------+-----------+----------------------------+
                      |
              +---------------+        +--------------+
              |   Document    |<------>|   History    |
              | annotations,  |        | undo / redo  |
              | classes, size |        |  snapshots   |
              +---------------+        +--------------+
                      |
         +------------+-------------+
         |                          |
  +-------------+           +----------------+
  |   storage   |           |    export      |
  | sidecar i/o |           | coco, yolo,    |
  +-------------+           | masks, pairs   |
                            +----------------+
```

## 2. Modules

| Module | Responsibility | Knows about tkinter |
|---|---|---|
| `labeler/config.py` | Constants, defaults, supported extensions, settings file | no |
| `labeler/model.py` | `Annotation`, `AnnotationClass`, `ClassTable`, `Document` | no |
| `labeler/geometry.py` | Polygon maths: area, hit test, simplify, resample, bbox | no |
| `labeler/raster.py` | Polygon to mask and mask back to polygons, brush stamps | no |
| `labeler/history.py` | Undo/redo stack over document snapshots | no |
| `labeler/storage.py` | Sidecar read/write, format guard, atomic replace | no |
| `labeler/imageloader.py` | Opening images, first-frame rule, pixel size metadata | no |
| `labeler/validation.py` | Quality checks over a document or a working set | no |
| `labeler/export.py` | COCO, YOLO, PNG masks, project bundle, training pair | no |
| `labeler/canvas.py` | `ImageCanvas`: view transform, compositing, picking | yes |
| `labeler/tools.py` | One class per tool, each a small gesture state machine | yes (events only) |
| `labeler/panels.py` | Class panel, annotation list, display controls, status bar | yes |
| `labeler/app.py` | `App`: window, menus, keyboard, working set, wiring | yes |
| `labeler.py` | Launcher. Argument parsing, friendly dependency errors | no |

Everything above the line `canvas.py` is pure Python with no user interface. That split is
deliberate: the parts worth testing, and the parts a script might want to reuse, do not
require a display.

## 3. Key decisions

### 3.1 tkinter rather than Qt

Requirement NFR-3 is that the tool installs with nothing but Pillow and numpy, both of which
this repository already depends on. tkinter ships with CPython on Windows, so the
application runs on a fresh machine after `pip install -r requirements.txt`. PyQt or wxPython
would be more comfortable to write against and would add a 60 MB dependency and a licence
question to a tool whose whole point is to be easy to hand to a pathologist.

The cost is real: tkinter has no scene graph, no built-in alpha blending on its canvas, and
no vector transforms. Section 3.3 is how that is worked around.

### 3.2 Polygons are the single representation

Brush and eraser are raster operations, but storing some annotations as polygons and others
as masks would mean every consumer handles two shapes, and a region painted with the brush
could not then be vertex-edited.

So the brush and the eraser rasterise the region they are modifying, apply the stamp, and
trace the result back to a polygon. Round-tripping costs precision at the boundary, which is
bounded by the simplification tolerance and is far below the precision of a human hand on a
glomerulus. What it buys is that every tool works on every region no matter what drew it
(FR-19), and that the sidecar stays small and readable (NFR-7).

The tracing code is `MaskPostProcessor` from the repository root, the same connected
components, hole filling and contour tracing the detector uses to turn model output into
polygons. Reusing it means the tool and the detector agree on what a polygon derived from a
mask looks like. `raster.py` imports it and raises a clear error if the tool has been copied
out of the repository without it.

### 3.3 Rendering: raster underneath, vectors on top

Each repaint does this:

1. Work out the rectangle of image space currently visible.
2. Crop the full-resolution PIL image to it and resize that crop to the viewport size.
3. Rasterise the filled regions into an RGBA overlay the size of the viewport and
   alpha-composite it onto the crop. This is where overlay transparency (FR-34) comes from,
   since the tkinter canvas cannot blend.
4. Convert to a `PhotoImage` and put it on the canvas as a single image item.
5. Draw outlines, vertex handles and the in-progress gesture as ordinary canvas line and
   oval items on top, where they stay crisp at any zoom and can be hit-tested cheaply.

Cropping before resizing is what keeps this fast at high zoom: the work is proportional to
the viewport, not to the image. A 1200 x 800 viewport repaints in a few milliseconds on a
2560 x 1920 image whether the zoom is 10 percent or 800 percent.

During a freehand drag the expensive path is skipped entirely and only the live stroke item
is updated, which is what NFR-5 needs.

### 3.4 Undo by snapshot, not by command

The undo stack holds deep copies of the annotation list. The alternative, a command object
per operation with an inverse, is more memory-efficient and considerably more code, and
every new tool becomes two implementations that can disagree.

Annotations are small: a few hundred coordinate pairs each. Fifty snapshots of a heavily
annotated image is on the order of a megabyte. The image itself is never in a snapshot.
Snapshot undo is correct by construction - it cannot drift from the operation it undoes -
and that matters more here than the memory.

### 3.5 Coordinates are image pixels

Stored coordinates are floats in full-resolution image pixel space. Not normalised, not
view space, not integers.

- Image pixels mean a coordinate can be read in the sidecar and checked against the image.
- Floats mean zooming in to place a vertex precisely is not quantised to whole pixels.
- Normalising is a division away for the formats that want it (YOLO, and the detector's own
  JSON), and the sidecar stores the image dimensions so that division is always possible.

The view transform lives only in `ImageCanvas` and is applied at draw time, which is what
FR-38 requires: no stored coordinate ever changes because of zoom or pan.

### 3.6 Sidecar per image, not a project file

A project file would centralise the annotations and make the working set explicit. It would
also mean annotations and images could be separated by a move or a copy, and that two people
annotating two halves of a folder would conflict.

A sidecar beside the image, named after the image, travels with it, merges trivially, is
obvious to find, and is what the user asked for. The cost is that there is no single file
representing the whole job, which is why export can produce one (FR-49).

Safety comes from two rules in `storage.py`: a `format` marker that must be present before
the tool will overwrite a file in the sidecar position (FR-43), and a write to a temporary
file followed by `os.replace`, which is atomic on Windows and POSIX alike (FR-44).

## 4. Data flow

### Opening an image

```
App.open_image(path)
  -> imageloader.load(path)          first frame, RGB, pixel size from OME metadata
  -> storage.load_sidecar(path)      or an empty Document if there is none
  -> Document.reconcile(classes)     adopt unknown class ids into the class table
  -> History.reset(document)
  -> ImageCanvas.set_image(...) ; zoom_to_fit() ; repaint
```

### Drawing a region

```
canvas event -> ToolHost.dispatch -> active Tool
  tool accumulates points in view space, converting to image space as it goes
  tool calls canvas.set_preview(...) for the live stroke
  on completion:
    History.push(document)           snapshot BEFORE the change
    Document.add(annotation)
    App.mark_dirty() ; canvas.repaint()
```

Snapshotting before the change, not after, is what makes the first undo return to the state
the user remembers.

### Switching image

```
App.goto(index)
  -> storage.save_sidecar(current)   FR-8, autosave, silent unless it fails
  -> open_image(next path)
```

## 5. Dependency rules

- `model`, `geometry`, `history`, `storage`, `validation`, `export`, `imageloader`,
  `raster` must not import tkinter, and must not import each other circularly. Permitted
  edges: `storage -> model`, `export -> model, geometry, raster, imageloader`,
  `validation -> model, geometry`, `model -> geometry`, `raster -> geometry`.
- `canvas`, `tools`, `panels` may import the pure modules and tkinter, and must not import
  `app`. The controller wires them together; they do not reach back for it. Where a tool
  needs to tell the application something, it does so through a callback the application
  supplied.
- `app` may import everything.

## 6. Error handling

- Anything the user did wrong is a dialog with a sentence that says what to do.
- Anything the tool did wrong that is survivable is a status-bar message and a full
  traceback on the console.
- A failed save is never silent, because the point of autosave is that it can be trusted.
- A sidecar that fails to parse is reported with its path, and the image opens empty; the
  broken file is not touched, so nothing is lost to a bad read.

## 7. What is deliberately absent

- No automatic or model-assisted labelling. The tool exists to produce ground truth, and
  ground truth seeded from a model's guesses is not independent of that model. If
  pre-labelling is ever added it must be visibly marked as unconfirmed.
- No multi-user, locking, or merge. One person, one folder.
- No image adjustment beyond zoom. Brightness or contrast changes alter what a person
  perceives as a boundary, and an annotation should not depend on a display setting.
