##############################################################################################
# Purpose: Launcher for the Histology Labeler.
#
#   python labeler.py                       open the folder used last
#   python labeler.py "C:\\path\\to\\image.tif"  open one image, with its folder as the working set
#   python labeler.py "C:\\path\\to\\folder"     open a folder
#
# Dependencies are checked here rather than left to an import traceback, because the person
# running this is annotating images, not debugging a Python environment.
##############################################################################################

import os
import sys


def _check_dependencies():
    missing = []
    try:
        import tkinter  # noqa: F401
    except ImportError:
        missing.append(
            "tkinter - ships with Python on Windows. If this is missing, reinstall Python "
            "from python.org and leave the tcl/tk option enabled.")
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow - install with: pip install Pillow")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy - install with: pip install numpy")
    return missing


def main():
    missing = _check_dependencies()
    if missing:
        print("The Histology Labeler needs the following:\n")
        for entry in missing:
            print("  * " + entry)
        print("\nOr install everything at once:  pip install -r requirements.txt")
        return 1

    initial = None
    if len(sys.argv) > 1:
        initial = os.path.abspath(sys.argv[1])
        if not os.path.exists(initial):
            print(f"Not found: {initial}")
            return 1

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from labeler.app import main as run

    run(initial)
    return 0


if __name__ == "__main__":
    sys.exit(main())
