# Glomeruli Detector Labeling Tool

**Histology Labeler** is a desktop tool for drawing region annotations on microscopy images by
hand, so that a new stain or a new scanner can be labelled and used to train the
[Glomeruli Detector](https://github.com/NandikaDevarajan/GlomeruliDetector).

The detector's local model learned from masks recovered from an earlier model's own drawings.
That works for images a model has already seen. For a modality it has never seen, such as a new
brightfield stain, there are no drawings to recover, so somebody has to draw the first ones.
This tool is for that.

- Polygon, freehand, rectangle, brush, eraser and vertex-editing tools
- Multiple classes you can add, rename and recolour
- Annotations saved automatically as a JSON sidecar beside each image
- Quality checks before every export
- Export to the detector's training-pair format, COCO, YOLO segmentation, binary PNG masks,
  or a single project JSON
- Reports areas in µm² when the image declares its pixel size

Pure Python: tkinter for the interface, plus Pillow and numpy.

---

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Running](#running)
- [Using the tool](#using-the-tool)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Where annotations are stored](#where-annotations-are-stored)
- [Classes](#classes)
- [Exporting](#exporting)
- [Pixel size](#pixel-size)
- [From labels to a working detector](#from-labels-to-a-working-detector)
- [Project layout](#project-layout)
- [Specifications](#specifications)
- [License](#license)

---

## Requirements

- Python 3 with **tkinter**. tkinter ships with the python.org installers on Windows; leave
  the *tcl/tk* option enabled when installing.
- [Pillow](https://pypi.org/project/Pillow/) >= 9.0
- [numpy](https://pypi.org/project/numpy/) >= 1.21
- `maskpostprocessor.py` from the
  [GlomeruliDetector](https://github.com/NandikaDevarajan/GlomeruliDetector) repository.
  The brush and eraser use it to turn painted masks back into polygons. It is the same
  routine the detector uses, so painted regions and predicted regions come out the same way.

The tool is developed and used on Windows. tkinter, Pillow and numpy all run on Linux and
macOS too, but those platforms have not been tested.

## Installation

```bash
git clone https://github.com/NandikaDevarajan/GlomeruliDetectorLabelingTool.git
cd GlomeruliDetectorLabelingTool
pip install -r requirements.txt
```

Then supply `maskpostprocessor.py` in one of two ways. Without it the application will not
start.

**Option A: copy the file.** Put `maskpostprocessor.py` from the GlomeruliDetector
repository in the root of this repository, next to `histology_labeler.py`.

**Option B: side-by-side checkout.** Clone the detector into a folder named `gdetector`
beside this repository:

```
<parent>/
├── gdetector/                         GlomeruliDetector checkout
└── GlomeruliDetectorLabelingTool/     this repository
```

```bash
git clone https://github.com/NandikaDevarajan/GlomeruliDetector.git ../gdetector
```

## Running

```bash
python histology_labeler.py
```

| Command | Opens |
|---|---|
| `python histology_labeler.py` | the folder used last |
| `python histology_labeler.py "C:\path\to\folder"` | every supported image in that folder |
| `python histology_labeler.py "C:\path\to\image.tif"` | that image, with its folder as the working set |

Opening a single image still loads its whole folder as the working set, so Next and Previous
work straight away. Supported formats are PNG, JPG/JPEG, TIF/TIFF and BMP. For multi-page TIFFs
only the first page is annotated, because the later pages are reduced-size thumbnails.

If a dependency is missing, the launcher lists what to install instead of showing a traceback.

## Using the tool

**Draw a region.** With **Freehand**, press, trace the boundary and release; the region closes
itself. With **Polygon**, click point by point, then double-click or press Enter to finish.
**Rectangle** drags out a box.

**Select and move.** Click a region with **Select** to pick it up, and drag it to move it.

**Reshape.** Switch to **Edit vertices**. Drag a handle to move a point, click anywhere on an
edge to insert a point, and right-click a handle to remove one.

**Paint and erase.** **Brush** and **Eraser** work on the selected region. Erasing through the
middle of a region leaves two regions, which is usually what you want when one outline has run
across two structures.

**Undo.** Everything can be undone with Ctrl+Z.

The single-letter tool keys (V, P, F, R, B, E, N) and Page Down for the next image are the
shortcuts to learn first. **Help > Keyboard Shortcuts** shows the full list in the app.

## Keyboard shortcuts

| Tools | |
|---|---|
| `V` | Select |
| `P` | Polygon |
| `F` | Freehand |
| `R` | Rectangle |
| `B` | Brush |
| `E` | Eraser |
| `N` | Edit vertices |

| Drawing | |
|---|---|
| Polygon | click to place points; double-click or `Enter` to close; `Backspace` removes the last point; `Esc` abandons the polygon |
| Freehand | press, trace the boundary, release |
| Brush | paints into the selected region, or starts a new one |
| Eraser | removes from the selected region; cutting it in two makes two regions |
| Vertices | drag a handle to move it; click an edge to insert a point; right-click a handle to delete it |
| `[` / `]` | brush smaller / larger |

| View | |
|---|---|
| Mouse wheel | zoom at the cursor |
| Middle-drag, or `Space` + drag | pan |
| `Ctrl+0` / `Ctrl+1` | zoom to fit / actual size |

| Images and files | |
|---|---|
| `Page Down` / `D` | next image |
| `Page Up` / `A` | previous image |
| `Ctrl+O` | open image |
| `Ctrl+Shift+O` | open folder |
| `Ctrl+S` | save now (saving is also automatic) |

| Regions | |
|---|---|
| `Delete` | delete the selected region |
| `Tab` | select the next region |
| `H` | hide or show regions |
| `Ctrl+Z` / `Ctrl+Y` (or `Ctrl+Shift+Z`) | undo / redo |
| `Esc` | deselect |

## Where annotations are stored

Each image's annotations are saved in a JSON file beside it, under the image's own name:

```
NewImages\71121_1.tif
NewImages\71121_1.json
```

- **Saving is automatic.** Annotations are written when you move to another image, open another
  file or folder, or close the window. Ctrl+S saves immediately.
- **Reopening restores them.** When you open the image again, its regions come back as editable
  outlines.
- **No empty files.** When you delete an image's last region, its JSON file is removed.
- **Other JSON files are left alone.** Every sidecar carries a `"format": "histology-labeler"`
  marker. If a `.json` file with the image's name already exists and was not written by this
  tool, the tool says so and does not overwrite it.
- **Image files are never changed.** The tool only reads them.

A trimmed sidecar looks like this:

```json
{
  "format": "histology-labeler",
  "version": 1,
  "image": { "file": "71121_1.tif", "width": 2560, "height": 1920, "pixel_size_um": 0.85 },
  "classes": [ { "id": 1, "name": "Glomerulus", "color": "#E6194B" } ],
  "annotations": [
    { "id": 1, "class_id": 1, "class_name": "Glomerulus",
      "points": [ [1173.63, 551.39], [1133.01, 497.22], [1140.53, 429.51] ] }
  ]
}
```

Coordinates are in full-resolution image pixels, with the origin at the top left.

## Classes

There are four classes to begin with:

| Class | Colour |
|---|---|
| Glomerulus | `#E6194B` |
| Sclerotic Glomerulus | `#3CB44B` |
| Partial Glomerulus | `#4363D8` |
| Other Region | `#F58231` |

You can add, rename, recolour and delete classes. The class list is remembered between sessions
in `settings.json`. Each sidecar also stores the classes it uses, so a file still makes sense on
a machine that has never seen your class list.

## Exporting

| Export | Output |
|---|---|
| **Training Pair** | `Data/<name>.tif` (clean copy) and `Train/<name>.tif` (every region outlined in pure red), the format the detector's training pipeline reads |
| **COCO** | one `annotations.json` with instance segmentation for the whole set |
| **YOLO segmentation** | `labels/<stem>.txt` with normalised coordinates, plus `classes.txt` and `data.yaml` |
| **Binary masks** | `masks/<stem>/region_<id>_<class>.png` per region and `masks/<stem>/class_<class>.png` per class |
| **Project JSON** | every sidecar in the working set in one file, for archiving or handing over |

### Quality checks

Every export runs the quality checks first.

- **Errors** stop the export until you choose to continue anyway:
  - a region with fewer than three points
  - a collapsed outline
  - a duplicate ID
  - a region entirely outside the image
- **Warnings** are listed but do not block, because each can be legitimate:
  - a region crossing the image edge
  - two regions overlapping
  - an image with no regions

Double-click a finding to jump to that image and region.

## Pixel size

When an image declares its pixel size, the status bar shows microns per pixel, and areas are
reported in µm² as well as pixels. When it does not, no micron figure is shown and areas are in
pixels only.

Pixel sizes vary between scanners, so check this figure. For example, the brightfield files
annotated so far declare **0.850 µm/px**, while the detector's `PIXEL_TO_MICRON_FACTOR` is
**0.7634**. Area scales with the square of that factor, so the detector's µm² figures for those
images read **19.3 % below true** and need multiplying by **1.24**.

## From labels to a working detector

Of the export formats, only **Training Pair** is read by the detector's training pipeline
(`ModelTrainer`). The others are for other tools. These are the steps from labelled images
to a retrained detector.

1. **Annotate.** About 15 to 20 images with glomeruli outlined is a useful minimum. Nine
   brightfield images labelled with this tool, trained alongside the existing fluorescence
   collection, reached **F1 0.92** on that stain with no glomeruli missed. Outline the
   glomerulus itself, not a box around it: the model learns the boundary you draw, and the
   areas in the detector's CSV are computed from it.

2. **Export > Training Pair**, into any folder. If more than one class is in use, you are
   asked which to include. The model has a single foreground channel, so every exported region
   is treated as "glomerulus" in training.

3. **Make the export visible to training.** A collection is any folder holding a `Data\` and a
   `Train\` sub-folder. The collections used are listed in `DATASET_ROOTS` at the top of
   `ModelTrainer\prepare_dataset.py`:

   ```python
   DATASET_ROOTS = [
       os.path.join(REPO_ROOT, "Images"),
       os.path.join(REPO_ROOT, "OldModel", "Images"),
   ]
   ```

   Either export straight into one of those folders, or export somewhere new and add that
   folder to the list. Training uses every collection at once, so nothing already labelled has
   to be moved, and the model learns all the stains together instead of forgetting the
   previous one.

4. **Rebuild and train.**

   ```bash
   cd ModelTrainer
   python prepare_dataset.py   # rebuilds every mask, overwriting the cache
   python train_model.py       # writes gdetector/models/glomeruli_unet.onnx + .json
   python evaluate.py          # found, missed, invented, and area error
   ```

   Always run `prepare_dataset.py` as its own command first. `train_model.py` also calls it,
   but without forcing a rebuild, so a corrected label on an image already in
   `training\dataset` would be skipped and the old mask used instead.

5. **Run the detector.** No change is needed in the application. `train_model.py` overwrites
   the model that `DETECTION_MODE = "local"` loads, so the detector uses the retrained model
   on its next run:

   ```bash
   cd gdetector
   python gdetector.py "C:\path\to\images"
   ```

Before step 4, also do these two things:

- **Hold some new images out.** `VALIDATION_STEMS` in `ModelTrainer\train_model.py` lists the
  images kept out of training so that the reported scores mean something. Add two or three of
  the new file names, without extensions, so the metrics cover the new stain too.
- **Train on the union, not the new images alone.** A model fine-tuned only on a new stain loses
  what it knew about the old one. Keep the other collections listed in `DATASET_ROOTS`, and
  check the image count the build prints: a collection whose folder has been moved or renamed
  is skipped without a warning.

## Project layout

```
GlomeruliDetectorLabelingTool/
├── histology_labeler.py   launcher: checks dependencies, then starts the app
├── requirements.txt
├── labeler/
│   ├── app.py             main window, menus, shortcuts, export dialogs
│   ├── canvas.py          zoomable image canvas and overlay rendering
│   ├── tools.py           select, polygon, freehand, rectangle, brush, eraser, vertex tools
│   ├── model.py           annotation, class and document model
│   ├── geometry.py        polygon maths and simplification
│   ├── raster.py          polygon <-> mask conversion (uses maskpostprocessor.py)
│   ├── history.py         snapshot-based undo / redo
│   ├── imageloader.py     image loading, multi-page TIFF handling, pixel-size metadata
│   ├── storage.py         JSON sidecar read / write
│   ├── export.py          Training Pair, COCO, YOLO, masks, project JSON
│   ├── validation.py      pre-export quality checks
│   ├── panels.py          class and region side panels
│   └── config.py          defaults, limits, settings.json handling
└── spec/
    ├── requirements.md    what the tool must do
    ├── architecture.md    how it is built and why
    └── design.md          interaction, sidecar format, export formats, validation rules
```

User preferences (classes, brush size, overlay opacity, last folder, window position) are
saved in `settings.json` next to `histology_labeler.py`. If the file is missing or unreadable,
the defaults are used.

## Specifications

The full specifications are in [`spec/`](spec/):

- [Requirements](spec/requirements.md)
- [Architecture](spec/architecture.md)
- [Design](spec/design.md)

## License

[MIT](LICENSE)
