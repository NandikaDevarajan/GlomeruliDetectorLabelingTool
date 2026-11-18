"""Histology Labeler - manual region annotation for microscopy images.

The modules below `canvas` are pure Python with no user interface, so the data model,
storage, geometry, validation and export can be used from a script without a display.
"""

from .config import TOOL_NAME, TOOL_VERSION

__all__ = ["TOOL_NAME", "TOOL_VERSION"]
