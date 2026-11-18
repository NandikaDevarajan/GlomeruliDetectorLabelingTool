# Histology Labeler

A desktop tool for drawing region annotations on microscopy images by hand, so that a new
stain or a new scanner can be labelled and trained on.

The detector in this repository learned from masks recovered from an earlier model's own
drawings. That works for images a model has already seen. For a modality it has never seen -
the brightfield images in NewImages, for instance - there are no drawings to recover, and
somebody has to draw the first ones. This is the tool for that.

Specifications are in spec/: requirements.md, architecture.md and design.md.


## Install and run

  pip install -r requirements.txt

Only Pillow and numpy. The interface uses tkinter, which ships with Python, so there is
nothing else to install.

  python histology_labeler.py                      reopen the folder used last
  python histology_labeler.py "C:\path\to\folder"  open a folder of images
  python histology_labeler.py "C:\path\image.tif"  open one image

Opening a single image still makes its whole folder the working set, so the next and previous
buttons work straight away.


## The basics

Draw a region with Freehand: press, trace the boundary, release. It closes itself. Or use
Polygon, clicking point by point, and double-click or press Enter to finish.

Click a region with Select to pick it up; drag it to move it. Switch to Edit vertices to pull
its boundary around: drag a handle to move a point, click anywhere on the edge to insert one,
right-click a handle to remove it.

Brush and Eraser work on whichever region is selected. Erasing through the middle of a region
leaves two regions, which is usually what you want when one outline has run across two
structures.

Everything undoes with Ctrl+Z.

Help > Keyboard Shortcuts has the full list. The ones worth learning first are the single
letters for the tools - V, P, F, R, B, E, N - and Page Down for the next image.


## Where annotations go

Beside the image, under the image's own name:

  NewImages\71121_1.tif
  NewImages\71121_1.json

Saving is automatic. Annotations are written whenever you move to another image and when you
close the window, so there is nothing to remember. Ctrl+S saves immediately if you want it.

Open the image again and the regions come back as editable outlines. Delete the last region
and the JSON file is removed, so an image with no regions never leaves an empty file behind.

The tool will not overwrite a JSON file it did not write. If "71121_1.json" is already there
and belongs to something else, it says so and leaves it alone.


## Classes

Four to begin with - Glomerulus, Sclerotic Glomerulus, Partial Glomerulus, Other Region - and
you can add, rename, recolour and delete your own. The class list is remembered between
sessions, and each JSON file also carries the classes it uses, so a file still makes sense on
a machine that has never seen your class list.


## Exporting

Export > Training Pair is the one that closes the loop with this repository. It writes:

  <folder>\Data\<name>.tif     a copy of the clean image
  <folder>\Train\<name>.tif    the same image with every region outlined in pure red

That is exactly the convention ModelTrainer/prepare_dataset.py reads. Point it at those two
folders, or copy them into Images/Data and Images/Train, and the regions you drew become
training masks with no change to the pipeline:

  cd ..\ModelTrainer
  python prepare_dataset.py
  python train_model.py
  python evaluate.py

Also available: COCO instance segmentation, YOLO segmentation, binary PNG masks per region
and per class, and a single project JSON holding the whole folder.

Every export runs the quality checks first. Errors - a region with fewer than three points, a
collapsed outline, a duplicate id, a region entirely off the image - stop the export until
you say otherwise. Warnings - a region crossing the image edge, two regions overlapping, an
image with nothing on it - are listed but do not block, because all three are legitimate.
Double-click any finding to jump to that image and region.


## Pixel size

The status bar shows microns per pixel when the image declares it, and areas are then
reported in square microns as well as pixels.

This is worth watching. The brightfield files declare 0.850 um/px, while the detector's
PIXEL_TO_MICRON_FACTOR is 0.7634. Area scales with the square of that factor, so the
detector's square-micron figures for those images read 19.3% below true and would need
multiplying by 1.24.
Where an image says nothing, the status bar shows no micron figure and areas are in pixels
only.


## From labels to a working detector

Training Pair is the only export the pipeline in this repository reads. The others are for
other tools. The whole route from drawing to detecting is:

1. Annotate. Roughly 15 to 20 images with glomeruli outlined is the useful minimum. The
   nine brightfield images drawn here, trained alongside the existing fluorescence
   collection, reached F1 0.92 on that stain with nothing missed. Outline the glomerulus
   itself, not a box round it -
   the model learns the boundary you draw, and the areas in the CSV come from it.

2. Export > Training Pair, into any folder. If more than one class has been used you are
   asked which to include, because the model has a single foreground channel: everything
   exported becomes "glomerulus" as far as training is concerned.

3. Put the exported folder where the training pipeline can see it. A collection is any
   folder holding a Data\ and a Train\ sub-folder, and the collections in use are listed in
   DATASET_ROOTS at the top of ModelTrainer\prepare_dataset.py:

     DATASET_ROOTS = [
         os.path.join(REPO_ROOT, "Images"),
         os.path.join(REPO_ROOT, "OldModel", "Images"),
     ]

   Either export straight into one of those folders, or export somewhere new and add that
   folder to the list. Training then uses every collection at once, which is the point:
   nothing already labelled has to be copied or moved, and the model learns all the stains
   together rather than forgetting the previous one.

4. Rebuild and train:

     cd ..\ModelTrainer
     python prepare_dataset.py     rebuilds every mask, overwriting the cache
     python train_model.py         writes gdetector\models\glomeruli_unet.onnx + .json
     python evaluate.py            found, missed, invented, and area error

   Run prepare_dataset.py explicitly, as its own command. train_model.py also calls it, but
   without forcing a rebuild, so a corrected label on an image already in training\dataset
   would be skipped and the old mask used instead. Correcting labels is the point of this
   tool, so this step is not optional.

5. Nothing to change in the application. train_model.py overwrites the model that
   DETECTION_MODE = "local" already loads, so gdetector uses the retrained model on its
   next run:

     cd ..\gdetector
     python gdetector.py "C:\path\to\images"

Two things worth doing before step 4:

Hold some of the new images out. VALIDATION_STEMS in ModelTrainer\train_model.py lists the
images kept out of training so the reported scores mean something. It currently names four
fluorescence images, so a new stain would be trained on and never measured. Add two or three
of the new file names, without extensions, so the metrics cover the new stain too.

Train on the union, not the new images alone. A model fine-tuned only on the new stain loses
what it knows about the old one. Leaving the other collections listed in DATASET_ROOTS is all
this takes - but check the count the build prints, because a collection whose folder has been
moved or renamed is skipped silently.
