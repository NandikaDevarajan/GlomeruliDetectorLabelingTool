##############################################################################################
# Purpose: Undo and redo, by keeping snapshots of the annotation list.
#
# A command-with-inverse design would use less memory, but every tool would then have two
# implementations that can disagree, and a wrong inverse corrupts work silently. Snapshots
# cannot drift from the operation they undo. Annotations are a few hundred coordinate pairs
# each and the image is never copied, so the memory is not worth the risk.
##############################################################################################

from .config import UNDO_DEPTH


class History:
    def __init__(self, depth=UNDO_DEPTH):
        self.depth = depth
        self._undo = []
        self._redo = []

    def reset(self, document):
        """Start again from the state of a freshly opened image."""
        self._undo = []
        self._redo = []

    def push(self, document):
        """Record the state BEFORE a change.

        Called at the start of every mutating operation, which is what makes the first undo
        return to the state the user remembers rather than to one change too few.
        """
        self._undo.append(document.snapshot())
        if len(self._undo) > self.depth:
            del self._undo[0:len(self._undo) - self.depth]
        self._redo = []

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self, document):
        """Step back, parking the state being left on the redo stack."""
        if not self._undo:
            return False
        self._redo.append(document.snapshot())
        document.restore(self._undo.pop())
        return True

    def redo(self, document):
        if not self._redo:
            return False
        self._undo.append(document.snapshot())
        document.restore(self._redo.pop())
        return True
