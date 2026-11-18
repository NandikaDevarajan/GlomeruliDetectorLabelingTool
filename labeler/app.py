##############################################################################################
# Purpose: The window, the menus, the working set, and the wiring between everything else.
#
# This is the only module that knows about all the others. The canvas draws, the tools handle
# gestures, the panels display, storage persists - and none of them call each other. They are
# connected here, which is what keeps any one of them replaceable.
#
# It is also the only place that decides when work is written to disk. The rule is simple and
# the user should never have to think about it: annotations are saved whenever the image they
# belong to stops being the one on screen, and when the application closes.
##############################################################################################

import os
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

from . import export as exporters
from . import imageloader, storage, validation
from .canvas import ImageCanvas
from .config import (MAX_BRUSH_RADIUS, MIN_BRUSH_RADIUS, PALETTE, TOOL_NAME, TOOL_VERSION,
                     ZOOM_STEP, load_settings, save_settings)
from .history import History
from .model import ClassTable, Document
from .panels import ClassDialog, ClassPanel, DisplayPanel, RegionPanel, StatusBar
from .storage import SidecarError
from .tools import TOOL_CLASSES, TOOL_KEYS

IMAGE_FILE_TYPES = [
    ("Images", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
    ("TIFF", "*.tif *.tiff"),
    ("All files", "*.*"),
]


class App(tk.Tk):
    def __init__(self, initial_path=None):
        super().__init__()
        self.title(TOOL_NAME)
        self.settings = load_settings()
        self.geometry(self._fit_to_screen(self.settings.get("window", "1400x900")))
        self.minsize(900, 600)

        self.class_table = ClassTable.from_list(self.settings.get("classes"))
        if not len(self.class_table):
            self.class_table.add("Glomerulus", PALETTE[0])
        self.active_class_id = self._valid_class_id(self.settings.get("active_class_id"))
        self.brush_radius = int(self.settings.get("brush_radius", 20))

        self.paths = []
        self.index = -1
        self.loaded = None
        self.document = None
        self.history = History()
        self.selected_id = None
        self.dirty = False
        self._panning = None
        self._space_held = False

        self._build_ui()
        self._bind_events()

        self.tools = {cls.name: cls(self) for cls in TOOL_CLASSES}
        self.tool = None
        self.set_tool("freehand")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, lambda: self._open_initial(initial_path))

    # =============================================================== construction

    def _fit_to_screen(self, text):
        """Keep a remembered window size on the screen it is being opened on.

        A size saved on a large monitor would otherwise push the status bar below the bottom
        of a laptop screen, where the user cannot see the measurements or drag it back.
        A remembered position is kept only while it still lands on the desktop.
        """
        size, _, offset = text.partition("+")
        try:
            width, height = (int(value) for value in size.lower().split("x"))
        except ValueError:
            width, height = 1400, 900
        width = max(900, min(width, self.winfo_screenwidth() - 60))
        height = max(600, min(height, self.winfo_screenheight() - 100))

        if offset:
            try:
                x, y = (int(value) for value in offset.split("+"))
                if 0 <= x <= self.winfo_screenwidth() - 200 and \
                        0 <= y <= self.winfo_screenheight() - 200:
                    return f"{width}x{height}+{x}+{y}"
            except ValueError:
                pass
        return f"{width}x{height}"

    def _build_ui(self):
        self._build_menu()

        toolbar = ttk.Frame(self, padding=(6, 4))
        toolbar.pack(side="top", fill="x")
        self._build_toolbar(toolbar)

        self.status_bar = StatusBar(self)
        self.status_bar.pack(side="bottom", fill="x")
        ttk.Separator(self, orient="horizontal").pack(side="bottom", fill="x")

        body = ttk.Frame(self)
        body.pack(side="top", fill="both", expand=True)

        side = ttk.Frame(body, padding=(6, 6))
        side.pack(side="right", fill="y")

        self.class_panel = ClassPanel(side, self.select_class, self.new_class,
                                      self.edit_class, self.delete_class)
        self.class_panel.pack(fill="x")

        self.region_panel = RegionPanel(side, self.select, self.toggle_visible,
                                        self.delete_region, self.reclass_region)
        self.region_panel.pack(fill="both", expand=True, pady=6)

        self.display_panel = DisplayPanel(side, self.apply_display)
        self.display_panel.pack(fill="x")
        self.display_panel.set_values(self.settings)

        self.canvas = ImageCanvas(body)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.class_table = self.class_table
        self.apply_display({
            "overlay_opacity": self.settings.get("overlay_opacity", 0.35),
            "show_fills": self.settings.get("show_fills", True),
            "show_outlines": self.settings.get("show_outlines", True),
            "show_labels": self.settings.get("show_labels", True),
        })
        self.class_panel.refresh(self.class_table, {}, self.active_class_id)

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Image...", accelerator="Ctrl+O",
                              command=self.open_file)
        file_menu.add_command(label="Open Folder...", accelerator="Ctrl+Shift+O",
                              command=self.open_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S",
                              command=lambda: self.save_current(silent=False))
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Delete Region", accelerator="Del",
                              command=lambda: self.delete_region(self.selected_id))
        edit_menu.add_command(label="Select Next Region", accelerator="Tab",
                              command=self.select_next)
        edit_menu.add_separator()
        edit_menu.add_command(label="Show All Regions", command=lambda: self.set_all_visible(True))
        edit_menu.add_command(label="Hide All Regions", command=lambda: self.set_all_visible(False))
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Zoom to Fit", accelerator="Ctrl+0",
                              command=self.canvas_fit)
        view_menu.add_command(label="Actual Size", accelerator="Ctrl+1",
                              command=lambda: self.canvas.zoom_to_actual())
        view_menu.add_separator()
        view_menu.add_command(label="Previous Image", accelerator="PgUp",
                              command=self.previous_image)
        view_menu.add_command(label="Next Image", accelerator="PgDn", command=self.next_image)
        menubar.add_cascade(label="View", menu=view_menu)

        self.images_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Images", menu=self.images_menu)

        export_menu = tk.Menu(menubar, tearoff=0)
        export_menu.add_command(label="Validate Annotations...", command=self.run_validation)
        export_menu.add_separator()
        export_menu.add_command(label="Training Pair (Data / Train)...",
                                command=lambda: self.run_export("training"))
        export_menu.add_command(label="COCO Instance Segmentation...",
                                command=lambda: self.run_export("coco"))
        export_menu.add_command(label="YOLO Segmentation...",
                                command=lambda: self.run_export("yolo"))
        export_menu.add_command(label="Binary PNG Masks...",
                                command=lambda: self.run_export("masks"))
        export_menu.add_command(label="Project JSON...",
                                command=lambda: self.run_export("project"))
        menubar.add_cascade(label="Export", menu=export_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Keyboard Shortcuts", command=self.show_shortcuts)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.configure(menu=menubar)

    def _build_toolbar(self, toolbar):
        self.tool_variable = tk.StringVar(value="freehand")
        for cls in TOOL_CLASSES:
            ttk.Radiobutton(toolbar, text=cls.label, value=cls.name,
                            variable=self.tool_variable, style="Toolbutton",
                            command=lambda name=cls.name: self.set_tool(name)
                            ).pack(side="left", padx=1)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(toolbar, text="Brush").pack(side="left")
        self.brush_variable = tk.IntVar(value=self.brush_radius)
        ttk.Scale(toolbar, from_=MIN_BRUSH_RADIUS, to=MAX_BRUSH_RADIUS, length=110,
                  variable=self.brush_variable,
                  command=lambda value: self.set_brush_radius(float(value))
                  ).pack(side="left", padx=4)
        self.brush_label = ttk.Label(toolbar, text=f"{self.brush_radius} px", width=7)
        self.brush_label.pack(side="left")

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(toolbar, text="<", width=3, command=self.previous_image).pack(side="left")
        self.counter_label = ttk.Label(toolbar, text="0 / 0", width=10, anchor="center")
        self.counter_label.pack(side="left")
        ttk.Button(toolbar, text=">", width=3, command=self.next_image).pack(side="left")

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Fit", width=5, command=self.canvas_fit).pack(side="left")
        ttk.Button(toolbar, text="1:1", width=5,
                   command=lambda: self.canvas.zoom_to_actual()).pack(side="left", padx=2)

    def _bind_events(self):
        canvas = self.canvas
        canvas.bind("<ButtonPress-1>", self._press)
        canvas.bind("<B1-Motion>", self._drag)
        canvas.bind("<ButtonRelease-1>", self._release)
        canvas.bind("<Motion>", self._motion)
        canvas.bind("<Double-Button-1>", self._double_click)
        canvas.bind("<ButtonPress-3>", self._right_click)
        canvas.bind("<ButtonPress-2>", self._pan_start)
        canvas.bind("<B2-Motion>", self._pan_move)
        canvas.bind("<ButtonRelease-2>", self._pan_end)
        canvas.bind("<MouseWheel>", self._wheel)
        canvas.bind("<Button-4>", lambda event: self._wheel_steps(event, 1))
        canvas.bind("<Button-5>", lambda event: self._wheel_steps(event, -1))
        canvas.bind("<Leave>", lambda event: canvas.set_brush_cursor(None))

        self.bind_all("<Control-z>", lambda event: self._shortcut(self.undo))
        self.bind_all("<Control-y>", lambda event: self._shortcut(self.redo))
        self.bind_all("<Control-Shift-Z>", lambda event: self._shortcut(self.redo))
        self.bind_all("<Control-s>", lambda event: self._shortcut(
            lambda: self.save_current(silent=False)))
        self.bind_all("<Control-o>", lambda event: self._shortcut(self.open_file))
        self.bind_all("<Control-O>", lambda event: self._shortcut(self.open_folder))
        self.bind_all("<Control-Key-0>", lambda event: self._shortcut(self.canvas_fit))
        self.bind_all("<Control-Key-1>", lambda event: self._shortcut(
            lambda: self.canvas.zoom_to_actual()))
        self.bind_all("<Key>", self._key)
        self.bind_all("<KeyRelease-space>", self._space_up)

    # ============================================================== tool context
    # The small interface the tools in tools.py are given. They see nothing else.

    def active_color(self):
        entry = self.class_table.get(self.active_class_id)
        return entry.color if entry else "#FFD966"

    def begin_change(self):
        if self.document is not None:
            self.history.push(self.document)

    def after_change(self):
        self.dirty = True
        self.refresh_panels()
        self.canvas.repaint()
        self._update_title()

    def select(self, annotation_id):
        self.selected_id = annotation_id
        self.canvas.selected_id = annotation_id
        self.region_panel.refresh(self.document, self.class_table, annotation_id,
                                  self._pixel_size())
        self.canvas.render_vectors()
        self._update_detail()

    def status(self, text):
        """What the tools report through. Named to match the context they are handed."""
        self.status_bar.set_message(text)

    # ================================================================ file handling

    def _open_initial(self, path):
        if path and os.path.isdir(path):
            self.load_folder(path)
        elif path and os.path.isfile(path):
            self.load_single(path)
        else:
            last = self.settings.get("last_folder")
            if last and os.path.isdir(last):
                self.load_folder(last)
            else:
                self.status_bar.set_message("File > Open Folder to begin")

    def open_file(self):
        path = filedialog.askopenfilename(title="Open image", filetypes=IMAGE_FILE_TYPES)
        if path:
            self.load_single(path)

    def open_folder(self):
        folder = filedialog.askdirectory(title="Open folder of images")
        if folder:
            self.load_folder(folder)

    def load_single(self, path):
        """Open one file, but keep its folder as the working set so navigation still works."""
        if not self.save_current():
            return
        folder = os.path.dirname(os.path.abspath(path))
        paths = imageloader.list_folder(folder)
        if path not in paths:
            paths = [path]
        self.paths = paths
        self.settings["last_folder"] = folder
        self.load_index(paths.index(path) if path in paths else 0)

    def load_folder(self, folder):
        if not self.save_current():
            return
        paths = imageloader.list_folder(folder)
        if not paths:
            messagebox.showinfo(TOOL_NAME, f"No supported images in\n{folder}")
            return
        self.paths = paths
        self.settings["last_folder"] = folder
        self.load_index(0)

    def load_index(self, index):
        if not self.paths:
            return
        index = max(0, min(len(self.paths) - 1, index))
        path = self.paths[index]
        try:
            loaded = imageloader.load(path)
        except (OSError, ValueError) as error:
            messagebox.showerror(TOOL_NAME, f"Could not open\n{path}\n\n{error}")
            return

        try:
            document = storage.load_sidecar(path, self.class_table, loaded.width,
                                            loaded.height, loaded.pixel_size_um)
        except SidecarError as error:
            messagebox.showwarning(TOOL_NAME, str(error))
            document = Document(os.path.basename(path), loaded.width, loaded.height,
                                loaded.pixel_size_um)

        self.index = index
        self.loaded = loaded
        self.document = document
        self.dirty = False
        self.history.reset(document)
        self.selected_id = None

        self.canvas.document = document
        self.canvas.class_table = self.class_table
        self.canvas.selected_id = None
        self.canvas.set_image(loaded)
        self.canvas.zoom_to_fit()

        if self.tool is not None:
            self.tool.cancel()
        self.refresh_panels()
        self._rebuild_images_menu()
        self._update_title()
        self._update_detail()

        if document.size_mismatch:
            messagebox.showwarning(
                TOOL_NAME,
                f"{os.path.basename(path)} is {loaded.width} x {loaded.height}, but its "
                f"annotations were saved against {document.size_mismatch[0]} x "
                f"{document.size_mismatch[1]}.\n\nThe regions are drawn at their stored "
                f"coordinates and will not line up. Check the image before editing them.")

        count = len(document.annotations)
        self.status_bar.set_message(
            f"{loaded.name}  -  {count} region{'' if count == 1 else 's'}"
            + ("  (loaded from sidecar)" if count else ""))

    def save_current(self, silent=True):
        """Write the sidecar. Returns False only if the user should be stopped."""
        if self.document is None or self.index < 0:
            return True
        if not self.dirty and not self.document.annotations:
            return True
        try:
            storage.save_sidecar(self.paths[self.index], self.document, self.class_table)
            self.dirty = False
            self._update_title()
            if not silent:
                self.status_bar.set_message(
                    f"Saved {os.path.basename(storage.sidecar_path(self.paths[self.index]))}")
            return True
        except SidecarError as error:
            # Autosave that fails quietly is worse than no autosave, because the user has
            # been told their work is being kept.
            return messagebox.askyesno(
                TOOL_NAME,
                f"{error}\n\nContinue anyway and lose the changes to this image?")

    def next_image(self):
        if self.paths and self.index < len(self.paths) - 1:
            if self.save_current():
                self.load_index(self.index + 1)

    def previous_image(self):
        if self.paths and self.index > 0:
            if self.save_current():
                self.load_index(self.index - 1)

    # ================================================================== editing

    def undo(self):
        if self.document is not None and self.history.undo(self.document):
            self.selected_id = None
            self.canvas.selected_id = None
            self.after_change()
            self.status_bar.set_message("Undo")

    def redo(self):
        if self.document is not None and self.history.redo(self.document):
            self.selected_id = None
            self.canvas.selected_id = None
            self.after_change()
            self.status_bar.set_message("Redo")

    def delete_region(self, annotation_id):
        if self.document is None or annotation_id is None:
            return
        self.begin_change()
        if self.document.remove(annotation_id):
            if self.selected_id == annotation_id:
                self.select(None)
            self.after_change()
            self.status_bar.set_message(f"Deleted region {annotation_id}")

    def toggle_visible(self, annotation_id):
        annotation = self.document.get(annotation_id) if self.document else None
        if annotation is None:
            return
        self.begin_change()
        annotation.visible = not annotation.visible
        self.after_change()

    def set_all_visible(self, visible):
        if self.document is None or not self.document.annotations:
            return
        self.begin_change()
        for annotation in self.document.annotations:
            annotation.visible = visible
        self.after_change()

    def reclass_region(self, annotation_id):
        annotation = self.document.get(annotation_id) if self.document else None
        if annotation is None:
            return
        annotation_class = self._ask_class(annotation.class_id)
        if annotation_class is None:
            return
        self.begin_change()
        annotation.class_id = annotation_class
        self.after_change()

    def select_next(self):
        if self.document is None or not self.document.annotations:
            return
        ids = [a.id for a in self.document.annotations]
        if self.selected_id in ids:
            self.select(ids[(ids.index(self.selected_id) + 1) % len(ids)])
        else:
            self.select(ids[0])
        self._frame_selected()

    def _frame_selected(self):
        """Zoom and pan onto the selected region, keeping the status bar in step."""
        annotation = self.document.get(self.selected_id) if self.document else None
        if annotation is not None:
            self.canvas.frame_box(annotation.bounding_box())
            self._update_detail()

    # ================================================================== classes

    def _valid_class_id(self, class_id):
        if class_id is not None and self.class_table.get(class_id) is not None:
            return int(class_id)
        return self.class_table.classes[0].id

    def select_class(self, class_id):
        self.active_class_id = class_id
        entry = self.class_table.get(class_id)
        if entry:
            self.status_bar.set_message(f"New regions will be {entry.name}")

    def new_class(self):
        dialog = ClassDialog(self, "New class", "", self.class_table.next_color(PALETTE))
        self.wait_window(dialog)
        if dialog.result:
            name, color = dialog.result
            entry = self.class_table.add(name, color)
            self.active_class_id = entry.id
            self.refresh_panels()

    def edit_class(self, class_id):
        entry = self.class_table.get(class_id)
        if entry is None:
            return
        dialog = ClassDialog(self, "Edit class", entry.name, entry.color)
        self.wait_window(dialog)
        if dialog.result:
            entry.name, entry.color = dialog.result
            self.refresh_panels()
            self.canvas.repaint()
            self.dirty = self.dirty or bool(self.document and self.document.annotations)

    def delete_class(self, class_id):
        if len(self.class_table) <= 1:
            messagebox.showinfo(TOOL_NAME, "There must be at least one class.")
            return
        in_use = self._count_class_usage(class_id)
        if in_use:
            # Silently reassigning would corrupt labelling nobody asked to change.
            messagebox.showinfo(
                TOOL_NAME,
                f"{in_use} region{'' if in_use == 1 else 's'} in the images loaded so far "
                f"still use this class. Change them to another class first.")
            return
        self.class_table.remove(class_id)
        self.active_class_id = self._valid_class_id(None)
        self.refresh_panels()

    def _count_class_usage(self, class_id):
        if self.document is None:
            return 0
        return sum(1 for a in self.document.annotations if a.class_id == class_id)

    def _ask_class(self, current_id):
        """A small modal list of classes. Returns the chosen id, or None."""
        dialog = tk.Toplevel(self)
        dialog.title("Change class")
        dialog.resizable(False, False)
        dialog.transient(self)
        chosen = {"id": None}

        listbox = tk.Listbox(dialog, height=min(10, len(self.class_table)), width=30,
                             activestyle="none")
        listbox.pack(padx=12, pady=(12, 6))
        ids = []
        for position, entry in enumerate(self.class_table):
            listbox.insert("end", entry.name)
            listbox.itemconfigure(position, foreground=entry.color)
            ids.append(entry.id)
            if entry.id == current_id:
                listbox.selection_set(position)

        def confirm():
            selection = listbox.curselection()
            if selection:
                chosen["id"] = ids[selection[0]]
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(pady=(0, 12))
        ttk.Button(buttons, text="OK", width=9, command=confirm).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", width=9, command=dialog.destroy).pack(side="left")
        listbox.bind("<Double-1>", lambda event: confirm())
        dialog.bind("<Return>", lambda event: confirm())
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.grab_set()
        self.wait_window(dialog)
        return chosen["id"]

    # ===================================================================== view

    def canvas_fit(self):
        self.canvas.zoom_to_fit()
        self._update_detail()

    def set_tool(self, name):
        if self.tool is not None:
            self.tool.deactivate()
        self.tool = self.tools[name]
        self.tool_variable.set(name)
        self.tool.activate()
        self.canvas.show_handles = self.tool.wants_handles
        self.canvas.configure(cursor=self.tool.cursor)
        if name not in ("brush", "eraser"):
            self.canvas.set_brush_cursor(None)
        self.canvas.render_vectors()
        self.status_bar.set_message(f"{self.tool.label} tool")

    def set_brush_radius(self, value):
        self.brush_radius = int(max(MIN_BRUSH_RADIUS, min(MAX_BRUSH_RADIUS, value)))
        self.brush_label.configure(text=f"{self.brush_radius} px")

    def apply_display(self, values):
        self.canvas.overlay_opacity = values["overlay_opacity"]
        self.canvas.show_fills = values["show_fills"]
        self.canvas.show_outlines = values["show_outlines"]
        self.canvas.show_labels = values["show_labels"]
        self.settings.update(values)
        self.canvas.repaint()

    def refresh_panels(self):
        counts = self.document.counts_by_class() if self.document else {}
        self.class_panel.refresh(self.class_table, counts, self.active_class_id)
        self.region_panel.refresh(self.document, self.class_table, self.selected_id,
                                  self._pixel_size())
        if self.paths:
            self.counter_label.configure(text=f"{self.index + 1} / {len(self.paths)}")
        self._update_detail()

    def _pixel_size(self):
        return self.document.pixel_size_um if self.document else None

    def _update_title(self):
        if self.loaded is None:
            self.title(TOOL_NAME)
            return
        self.title(f"{'*' if self.dirty else ''}{self.loaded.name} - {TOOL_NAME}")

    def _update_detail(self):
        if self.loaded is None:
            self.status_bar.set_detail("")
            return
        parts = [f"{self.loaded.width} x {self.loaded.height}"]
        if self.loaded.pixel_size_um:
            parts.append(f"{self.loaded.pixel_size_um:.3f} um/px")
        parts.append(f"zoom {self.canvas.zoom * 100:.0f}%")
        annotation = self.document.get(self.selected_id) if self.document else None
        if annotation is not None:
            area = annotation.area_pixels
            text = f"region {annotation.id}: {area:,.0f} px"
            if self.loaded.pixel_size_um:
                text += f" / {area * self.loaded.pixel_size_um ** 2:,.0f} um2"
            parts.append(text)
        self.status_bar.set_detail("   ".join(parts))

    def _rebuild_images_menu(self):
        self.images_menu.delete(0, "end")
        for position, path in enumerate(self.paths[:300]):
            count = storage.peek_count(path) if position != self.index else len(self.document)
            marker = f"  [{count}]" if count else ""
            self.images_menu.add_command(
                label=f"{position + 1}. {os.path.basename(path)}{marker}",
                command=lambda index=position: self._goto(index))
        if len(self.paths) > 300:
            self.images_menu.add_separator()
            self.images_menu.add_command(label=f"... and {len(self.paths) - 300} more",
                                         state="disabled")

    def _goto(self, index):
        if self.save_current():
            self.load_index(index)

    # ================================================================== gestures

    def _point(self, event):
        return self.canvas.to_image(event.x, event.y)

    def _press(self, event):
        self.canvas.focus_set()
        if self._space_held:
            self._pan_start(event)
            return
        if self.document is not None:
            self.tool.on_press(self._point(event), event)

    def _drag(self, event):
        if self._panning is not None:
            self._pan_move(event)
            return
        if self.document is not None:
            self.tool.on_drag(self._point(event), event)

    def _release(self, event):
        if self._panning is not None:
            self._pan_end(event)
            return
        if self.document is not None:
            self.tool.on_release(self._point(event), event)
            self._update_detail()

    def _motion(self, event):
        if self.document is not None:
            self.tool.on_motion(self._point(event), event)

    def _double_click(self, event):
        if self.document is not None:
            self.tool.on_double_click(self._point(event), event)

    def _right_click(self, event):
        if self.document is not None:
            self.tool.on_right_click(self._point(event), event)

    def _pan_start(self, event):
        self._panning = (event.x, event.y)
        self.canvas.configure(cursor="fleur")

    def _pan_move(self, event):
        if self._panning is None:
            return
        self.canvas.pan_by(event.x - self._panning[0], event.y - self._panning[1])
        self._panning = (event.x, event.y)

    def _pan_end(self, _event):
        self._panning = None
        self.canvas.configure(cursor=self.tool.cursor if self.tool else "arrow")

    def _wheel(self, event):
        self._wheel_steps(event, event.delta / 120.0)

    def _wheel_steps(self, event, steps):
        self.canvas.zoom_by(ZOOM_STEP ** steps, event.x, event.y)
        self._update_detail()

    def _shortcut(self, action):
        action()
        return "break"

    def _space_up(self, _event):
        self._space_held = False
        if self._panning is None and self.tool is not None:
            self.canvas.configure(cursor=self.tool.cursor)

    def _key(self, event):
        # Typing in a dialog or an entry must never reach the tool shortcuts.
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
            return None
        # Control and Alt combinations have their own bindings.
        if event.state & 0x0004:
            return None

        keysym = event.keysym
        if keysym == "space":
            self._space_held = True
            self.canvas.configure(cursor="fleur")
            return "break"

        if self.tool is not None and self.tool.on_key(keysym):
            return "break"

        lowered = keysym.lower()
        if lowered in TOOL_KEYS:
            self.set_tool(TOOL_KEYS[lowered])
            return "break"
        if keysym == "Delete":
            self.delete_region(self.selected_id)
            return "break"
        if keysym == "Escape":
            self.select(None)
            return "break"
        if keysym == "Tab":
            self.select_next()
            return "break"
        if keysym in ("Next", "d"):
            self.next_image()
            return "break"
        if keysym in ("Prior", "a"):
            self.previous_image()
            return "break"
        if keysym == "h":
            self.toggle_visible(self.selected_id)
            return "break"
        if keysym == "bracketleft":
            self._nudge_brush(-4)
            return "break"
        if keysym == "bracketright":
            self._nudge_brush(4)
            return "break"
        return None

    def _nudge_brush(self, delta):
        self.set_brush_radius(self.brush_radius + delta)
        self.brush_variable.set(self.brush_radius)

    # ================================================= validation and exporting

    def _collect_items(self):
        """(path, document) for every image in the working set.

        The open image uses the in-memory document, which may hold changes that are not on
        disk yet; the rest are read from their sidecars.
        """
        items = []
        for position, path in enumerate(self.paths):
            if position == self.index and self.document is not None:
                items.append((path, self.document))
                continue
            try:
                document = storage.load_sidecar(path, self.class_table)
            except SidecarError:
                continue
            if document.annotations:
                items.append((path, document))
        return items

    def run_validation(self):
        if not self.paths:
            return
        self.save_current()
        findings = validation.validate_set(self._collect_items())
        self._show_findings(findings, "Validation")
        return findings

    def _show_findings(self, findings, title):
        errors, warnings = validation.summarise(findings)
        dialog = tk.Toplevel(self)
        dialog.title(f"{title} - {errors} errors, {warnings} warnings")
        dialog.geometry("760x420")
        dialog.transient(self)

        tree = ttk.Treeview(dialog, columns=("severity", "image", "message"),
                            show="headings", selectmode="browse")
        for column, heading, width in (("severity", "", 70), ("image", "Image", 220),
                                       ("message", "Finding", 440)):
            tree.heading(column, text=heading)
            tree.column(column, width=width, stretch=(column == "message"))
        tree.tag_configure("error", foreground="#C00000")
        tree.tag_configure("warning", foreground="#B07000")

        scroll = ttk.Scrollbar(dialog, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True, padx=(8, 0), pady=8)

        if not findings:
            tree.insert("", "end", values=("ok", "", "No problems found"))
        for position, finding in enumerate(findings):
            tree.insert("", "end", iid=str(position),
                        values=(finding.severity,
                                os.path.basename(finding.image_path or ""),
                                finding.message),
                        tags=(finding.severity,))

        def jump(_event=None):
            selection = tree.selection()
            if not selection:
                return
            finding = findings[int(selection[0])]
            if finding.image_path and finding.image_path in self.paths:
                self._goto(self.paths.index(finding.image_path))
                if finding.annotation_id is not None:
                    self.select(finding.annotation_id)
                    self._frame_selected()

        tree.bind("<Double-1>", jump)
        ttk.Label(dialog, text="Double-click a finding to open that image and region.",
                  padding=(8, 0, 8, 8)).pack(side="bottom", anchor="w")

    def _ask_export_classes(self, items):
        """Which classes a training pair should outline. Returns a set of ids, or None.

        The detector is a single-channel segmentation model: everything outlined in the
        Train image becomes one foreground class. So a file that distinguishes sclerotic
        from healthy glomeruli has to be told which of those the model is being taught, and
        that decision cannot be inferred from the labels themselves.
        """
        used = {}
        for _, document in items:
            for annotation in document.annotations:
                used[annotation.class_id] = used.get(annotation.class_id, 0) + 1
        if not used:
            return None
        if len(used) == 1:
            return set(used)

        dialog = tk.Toplevel(self)
        dialog.title("Classes to export")
        dialog.resizable(False, False)
        dialog.transient(self)
        result = {"ids": None}

        ttk.Label(dialog, wraplength=380, padding=(12, 12, 12, 6),
                  text="The model has one foreground class, so every region exported here "
                       "is taught as a glomerulus. Choose which classes to include.").pack()

        variables = {}
        body = ttk.Frame(dialog, padding=(20, 0, 20, 8))
        body.pack(fill="x")
        for entry in self.class_table:
            if entry.id not in used:
                continue
            variable = tk.BooleanVar(value=True)
            variables[entry.id] = variable
            ttk.Checkbutton(body, variable=variable,
                            text=f"{entry.name}  ({used[entry.id]} regions)").pack(anchor="w")

        def confirm():
            chosen = {class_id for class_id, variable in variables.items() if variable.get()}
            if not chosen:
                return
            result["ids"] = chosen
            dialog.destroy()

        buttons = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        buttons.pack()
        ttk.Button(buttons, text="Export", width=10, command=confirm).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", width=10,
                   command=dialog.destroy).pack(side="left")
        dialog.bind("<Return>", lambda event: confirm())
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.grab_set()
        self.wait_window(dialog)
        return result["ids"]

    def run_export(self, kind):
        if not self.paths:
            return
        self.save_current()
        items = self._collect_items()
        if not items:
            messagebox.showinfo(TOOL_NAME, "Nothing to export - no regions have been drawn.")
            return

        findings = validation.validate_set(items)
        errors, _ = validation.summarise(findings)
        if errors:
            self._show_findings(findings, "Validation")
            if not messagebox.askyesno(
                    TOOL_NAME,
                    f"{errors} error{'' if errors == 1 else 's'} found. Export anyway?"):
                return

        training_classes = None
        if kind == "training":
            training_classes = self._ask_export_classes(items)
            if training_classes is None:
                return

        if kind == "project":
            target = filedialog.asksaveasfilename(
                title="Export project JSON", defaultextension=".json",
                filetypes=[("JSON", "*.json")], initialfile="annotations_project.json")
        else:
            target = filedialog.askdirectory(title="Choose a folder to export into")
        if not target:
            return

        try:
            if kind == "coco":
                message = exporters.export_coco(items, self.class_table, target)
            elif kind == "yolo":
                message = exporters.export_yolo(items, self.class_table, target)
            elif kind == "masks":
                message = exporters.export_masks(items, self.class_table, target)
            elif kind == "project":
                message = exporters.export_project(items, self.class_table, target)
            else:
                message = exporters.export_training_pair(items, self.class_table, target,
                                                         class_ids=training_classes)
        except Exception as error:  # noqa: BLE001 - a failed export must not kill the session
            traceback.print_exc()
            messagebox.showerror(TOOL_NAME, f"Export failed:\n\n{error}")
            return

        self.status_bar.set_message(f"Exported: {message}")
        messagebox.showinfo(TOOL_NAME, f"Export complete.\n\n{message}")

    # ====================================================================== help

    def show_shortcuts(self):
        messagebox.showinfo(f"{TOOL_NAME} - shortcuts", SHORTCUTS)

    def show_about(self):
        messagebox.showinfo(
            TOOL_NAME,
            f"{TOOL_NAME} {TOOL_VERSION}\n\n"
            f"Manual region annotation for microscopy images.\n"
            f"Annotations are stored as JSON beside each image, under the image's own name.\n\n"
            f"Export a training pair to feed ModelTrainer/prepare_dataset.py directly.")

    # ===================================================================== close

    def on_close(self):
        if not self.save_current(silent=True):
            return
        self.settings["classes"] = self.class_table.to_list()
        self.settings["active_class_id"] = self.active_class_id
        self.settings["brush_radius"] = self.brush_radius
        try:
            self.settings["window"] = self.winfo_geometry()
        except tk.TclError:
            pass
        save_settings(self.settings)
        self.destroy()


SHORTCUTS = """Tools
  V  Select          P  Polygon        F  Freehand      R  Rectangle
  B  Brush           E  Eraser         N  Edit vertices

Drawing
  Polygon   click to place points, double-click or Enter to close
            Backspace removes the last point, Escape abandons
  Freehand  press, trace the boundary, release
  Brush     paints into the selected region, or starts a new one
  Eraser    removes from the selected region; splitting it makes two regions
  Vertices  drag a handle to move it, click an edge to insert one,
            right-click a handle to delete it

View
  Wheel            zoom at the cursor
  Middle drag      pan
  Space + drag     pan
  Ctrl+0 / Ctrl+1  zoom to fit / actual size

Images
  Page Down / D    next image        Page Up / A    previous image
  Ctrl+S           save now (saving is automatic when switching images)

Regions
  Delete   delete selected     Tab   select next     H   hide or show
  Ctrl+Z   undo                Ctrl+Y   redo         Escape   deselect
  [ / ]    brush smaller / larger"""


def main(initial_path=None):
    app = App(initial_path)
    app.mainloop()
