# Histology Labeler - Requirements

Version 1.0 - Windows desktop - offline first

## 1. Purpose

A standalone desktop application for hand-drawing region-of-interest annotations on
microscopy and histopathology images, so that a human can produce or correct the ground
truth a segmentation model is trained on.

The immediate need is the one this repository has: the local glomeruli model was trained on
masks recovered from an earlier model's own drawings, which only works for images a model
has already seen. A new stain, or a new scanner, has no such drawings. This tool is how the
first annotations for a new modality get made.

## 2. Scope

In scope: opening images, drawing and editing polygon annotations, assigning them to
classes, storing them beside the image, and exporting them into the formats a training
pipeline reads.

Out of scope: training, inference, model evaluation, image enhancement, stitching, and any
form of automatic or assisted labelling. The tool records what a person decides; it does not
have an opinion about where a glomerulus is.

## 3. Definitions

| Term | Meaning |
|---|---|
| Annotation | One outlined region, belonging to exactly one class |
| Class | A named category with a colour, for example Glomerulus |
| Sidecar | The JSON file holding the annotations for one image |
| Document | The in-memory annotations for the image currently open |
| Image space | Pixel coordinates of the full-resolution image, origin top left |
| View space | Pixel coordinates of the on-screen canvas |

## 4. Functional requirements

### 4.1 Image management

- **FR-1** Open a single image file chosen by the user.
- **FR-2** Open a folder and treat every supported image in it as a working set, sorted by
  name. Sub-folders are not descended into.
- **FR-3** Support PNG, JPG, JPEG, TIF, TIFF and BMP.
- **FR-4** For multi-page TIFFs, annotate the first page. Later pages in this repository's
  images are reduced-size thumbnails, and annotating one would record coordinates at the
  wrong scale.
- **FR-5** Display the file name, the pixel dimensions, and the position in the working set.
- **FR-6** Move to the previous and next image in the working set, by button and by keyboard.
- **FR-7** Keep annotation state per image for the whole session.
- **FR-8** Save the current image's annotations automatically before switching away from it,
  before opening a different file or folder, and before the application closes.
- **FR-9** Show, for every image in the working set, whether it has saved annotations, how
  many, and whether it has unsaved changes.
- **FR-10** Never modify the image file itself. The tool is read-only with respect to the
  pixels it was given.

### 4.2 Annotation tools

- **FR-11 Polygon** - click to place vertices one at a time; double-click, Enter, or
  right-click closes the region; Backspace removes the last vertex; Escape abandons it.
- **FR-12 Freehand** - press, drag along the boundary, release. The traced path is closed
  automatically and thinned so that a slow hand does not produce ten thousand vertices.
- **FR-13 Rectangle** - press and drag to produce a four-vertex axis-aligned region.
- **FR-14 Brush** - paint with a circular brush of adjustable size. Painting adds to the
  selected annotation, or starts a new one if nothing is selected.
- **FR-15 Eraser** - remove painted area from the selected annotation. If erasing separates
  a region into disconnected parts, each part becomes its own annotation. If it removes the
  region entirely, the annotation is deleted.
- **FR-16 Select** - click a region to select it; click the background to deselect. Dragging
  a selected region moves it as a whole.
- **FR-17 Edit vertices** - with a region selected, drag a vertex to move it, click an edge
  to insert a vertex there, and right-click a vertex to delete it. A region may never be
  reduced below three vertices.
- **FR-18 Delete** - delete the selected region.
- **FR-19** Every drawing tool produces a closed region. A region is stored as a closed
  polygon regardless of which tool drew it, so that all tools remain interchangeable on the
  same region afterwards.

### 4.3 Region editing

- **FR-20** Every region is independently selectable and editable, whenever it was drawn.
- **FR-21** A selected region displays its boundary and its vertex handles.
- **FR-22** Undo and redo cover every operation that changes annotations: create, move,
  reshape, paint, erase, delete, class change, and visibility change.
- **FR-23** Undo history is per image and holds at least 50 steps.
- **FR-24** Change the class of a selected region.
- **FR-25** Change the colour of a class, applying to every region of that class.
- **FR-26** Hide and show an individual region, and hide or show all of them at once.
- **FR-27** Delete an individual region.

### 4.4 Class management

- **FR-28** Ship with the classes Glomerulus, Sclerotic Glomerulus, Partial Glomerulus and
  Other Region.
- **FR-29** Create, rename, recolour and delete classes.
- **FR-30** Deleting a class that is in use must be refused, with the count of regions that
  still use it, rather than silently orphaning them.
- **FR-31** The class list persists between sessions.
- **FR-32** Every annotation carries a unique id within its image, a class id, a class name,
  its polygon coordinates, its area in pixels, and an optional free-text note.

### 4.5 Visualisation

- **FR-33** Draw regions over the image, each in its class colour.
- **FR-34** Adjustable overlay transparency, from invisible to opaque.
- **FR-35** Toggle region outlines independently of fills.
- **FR-36** Display the number of regions per class.
- **FR-37** Display the area of the selected region in pixels, and also in square microns
  when the pixel size is known.
- **FR-38** Zoom and pan. Zooming and panning change what is on screen and never change a
  stored coordinate.
- **FR-39** Zoom to fit, and zoom to 100 percent, in one action each.

### 4.6 Storage

- **FR-40** Annotations are stored in a JSON sidecar in the same folder as the image, named
  after the image: `64464 Merged 4_RGB.tif` produces `64464 Merged 4_RGB.json`.
- **FR-41** Opening an image whose sidecar exists loads its regions and displays them
  immediately as closed, editable overlays.
- **FR-42** The sidecar records the image file name and pixel dimensions. If the image has
  since been resized, the mismatch must be reported rather than drawn at the wrong scale.
- **FR-43** The tool must refuse to overwrite a JSON file in the sidecar position that it
  did not write, identified by a format marker inside the file.
- **FR-44** A save must not be able to destroy the previous sidecar: write to a temporary
  file and replace the original only once the write has succeeded.
- **FR-45** An image with no regions saves no sidecar, and an existing sidecar whose last
  region is deleted is removed.

### 4.7 Export

- **FR-46** COCO instance segmentation JSON for the whole working set.
- **FR-47** YOLO segmentation: one text file per image with normalised coordinates, plus the
  class index file.
- **FR-48** Binary PNG masks: one per region, plus one combined mask per class per image.
- **FR-49** Native project JSON: every sidecar in the working set collected into one file
  that can be reopened.
- **FR-50** Training pair: for each annotated image, a copy of the clean image and a copy
  with every region outlined in pure red, written into `Data/` and `Train/` sub-folders.
  This is the convention `ModelTrainer/prepare_dataset.py` in this repository already reads, so
  an export of this kind is directly trainable.
- **FR-51** Export covers every annotated image in the working set, not only the open one.

### 4.8 Validation

- **FR-52** Run before every export, and on demand.
- **FR-53** Report: regions with fewer than three distinct points; regions with zero area;
  non-finite or out-of-range coordinates; regions lying wholly or partly outside the image;
  duplicate region ids; overlapping regions; images in the working set with no regions.
- **FR-54** Classify each finding as an error or a warning. Errors block export until fixed
  or until the user explicitly chooses to export anyway; warnings do not block.
- **FR-55** Selecting a finding navigates to the image and region it refers to.

## 5. Non-functional requirements

- **NFR-1** Runs offline. No network access at any point, for any reason.
- **NFR-2** Python 3.9 or newer on Windows 10/11. Should also run on macOS and Linux, since
  nothing in it is Windows-specific, but Windows is what is tested.
- **NFR-3** Depends only on Pillow, numpy and the standard library. The user interface uses
  tkinter, which ships with Python, so there is no toolkit to install.
- **NFR-4** Opens a 2560 x 1920 image in under two seconds, and pans and zooms it without
  visible lag.
- **NFR-5** Freehand drawing follows the cursor smoothly at full image resolution.
- **NFR-6** A crash, a power loss, or a forced close may cost at most the regions drawn since
  the last image switch; it may never corrupt a sidecar that was already on disk.
- **NFR-7** The sidecar format is plain, readable JSON that a person can inspect and a script
  can parse without this application.

## 6. Acceptance criteria

The tool is finished when, starting from a folder of unannotated TIFFs, a user can:

1. Open the folder and see the first image.
2. Draw a freehand region around a glomerulus and see it close into an editable polygon.
3. Drag two of its vertices to tighten the boundary.
4. Move to the next image and back, and find the region exactly as left.
5. Close the application, reopen it, open the same folder, and find the region still there.
6. Export a training pair and have `ModelTrainer/prepare_dataset.py` recover the same regions
   from it without modification.
