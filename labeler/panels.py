##############################################################################################
# Purpose: The three side panels and the status bar.
#
# Each panel owns its widgets and nothing else. They are told what to display through refresh()
# and report what the user did through callbacks the application supplied; none of them reaches
# back into the application, reads the document, or changes anything.
##############################################################################################

import tkinter as tk
from tkinter import colorchooser, ttk

SWATCH = "■"


class ClassPanel(ttk.LabelFrame):
    """The class list: which class new regions get, and how many regions each class holds."""

    def __init__(self, master, on_select, on_new, on_edit, on_delete):
        super().__init__(master, text="Classes", padding=(6, 4))
        self.on_select = on_select
        self.on_new = on_new
        self.on_edit = on_edit
        self.on_delete = on_delete
        self._ids = []

        self.tree = ttk.Treeview(self, columns=("count",), show="tree headings", height=6,
                                 selectmode="browse")
        self.tree.heading("#0", text="Class")
        self.tree.heading("count", text="n")
        self.tree.column("#0", width=170, stretch=True)
        self.tree.column("count", width=36, anchor="e", stretch=False)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.tree.bind("<Double-1>", lambda event: self._edit())
        self._shown = None

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(buttons, text="New", width=7, command=self.on_new).pack(side="left")
        ttk.Button(buttons, text="Edit", width=7, command=self._edit).pack(side="left", padx=3)
        ttk.Button(buttons, text="Delete", width=8, command=self._delete).pack(side="left")

    def _selected(self, _event=None):
        # Tk delivers <<TreeviewSelect>> after the call that caused it, so a selection this
        # panel set itself arrives looking exactly like a click. Comparing against what was
        # last displayed is what tells the two apart; a flag cannot, because it has already
        # been cleared by the time the event is delivered.
        selection = self.tree.selection()
        if not selection:
            return
        chosen = int(selection[0])
        if chosen == self._shown:
            return
        self._shown = chosen
        self.on_select(chosen)

    def _edit(self):
        selection = self.tree.selection()
        if selection:
            self.on_edit(int(selection[0]))

    def _delete(self):
        selection = self.tree.selection()
        if selection:
            self.on_delete(int(selection[0]))

    def refresh(self, class_table, counts, active_class_id):
        self._shown = active_class_id
        self.tree.delete(*self.tree.get_children())
        self._ids = []
        for entry in class_table:
            self.tree.insert("", "end", iid=str(entry.id),
                             text=f"{SWATCH}  {entry.name}",
                             values=(counts.get(entry.id, 0),),
                             tags=(f"class{entry.id}",))
            self.tree.tag_configure(f"class{entry.id}", foreground=entry.color)
            self._ids.append(entry.id)
        if active_class_id is not None and str(active_class_id) in self.tree.get_children():
            self.tree.selection_set(str(active_class_id))


class RegionPanel(ttk.LabelFrame):
    """Every region on the current image, with its class and its area."""

    def __init__(self, master, on_select, on_toggle, on_delete, on_reclass):
        super().__init__(master, text="Regions", padding=(6, 4))
        self.on_select = on_select
        self.on_toggle = on_toggle
        self.on_delete = on_delete
        self.on_reclass = on_reclass
        self._shown = None

        columns = ("class", "area")
        self.tree = ttk.Treeview(self, columns=columns, show="tree headings", height=10,
                                 selectmode="browse")
        self.tree.heading("#0", text="#")
        self.tree.heading("class", text="Class")
        self.tree.heading("area", text="Area")
        self.tree.column("#0", width=42, stretch=False)
        self.tree.column("class", width=118, stretch=True)
        self.tree.column("area", width=78, anchor="e", stretch=False)
        self.tree.tag_configure("hidden", foreground="#999999")

        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="top", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._selected)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(buttons, text="Hide/Show", width=10,
                   command=lambda: self._act(self.on_toggle)).pack(side="left")
        ttk.Button(buttons, text="Class...", width=8,
                   command=lambda: self._act(self.on_reclass)).pack(side="left", padx=3)
        ttk.Button(buttons, text="Delete", width=8,
                   command=lambda: self._act(self.on_delete)).pack(side="left")

    def _selected(self, _event=None):
        # See the note in ClassPanel._selected: the echo of a selection this panel set is
        # indistinguishable from a click except by its value.
        selection = self.tree.selection()
        if not selection:
            return
        chosen = int(selection[0])
        if chosen == self._shown:
            return
        self._shown = chosen
        self.on_select(chosen)

    def _act(self, callback):
        selection = self.tree.selection()
        if selection:
            callback(int(selection[0]))

    def refresh(self, document, class_table, selected_id, pixel_size_um=None):
        # Recorded before the tree is touched, so any event this rebuild queues is already
        # recognisable as an echo by the time Tk delivers it.
        self._shown = selected_id
        self.tree.delete(*self.tree.get_children())
        if document is None:
            return
        for annotation in document.annotations:
            entry = class_table.get(annotation.class_id)
            area = annotation.area_pixels
            if pixel_size_um:
                area_text = f"{area * pixel_size_um ** 2:,.0f} um2"
            else:
                area_text = f"{area:,.0f} px"
            tags = [f"class{annotation.class_id}"]
            if not annotation.visible:
                tags.append("hidden")
            self.tree.insert("", "end", iid=str(annotation.id),
                             text=str(annotation.id),
                             values=(entry.name if entry else "?", area_text),
                             tags=tuple(tags))
            if entry is not None and annotation.visible:
                self.tree.tag_configure(f"class{annotation.class_id}",
                                        foreground=entry.color)
        if selected_id is not None and str(selected_id) in self.tree.get_children():
            self.tree.selection_set(str(selected_id))
            self.tree.see(str(selected_id))


class DisplayPanel(ttk.LabelFrame):
    """Overlay transparency and what is drawn."""

    def __init__(self, master, on_change):
        super().__init__(master, text="Display", padding=(6, 4))
        self.on_change = on_change

        self.opacity = tk.DoubleVar(value=0.35)
        self.show_fills = tk.BooleanVar(value=True)
        self.show_outlines = tk.BooleanVar(value=True)
        self.show_labels = tk.BooleanVar(value=True)

        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="Opacity").pack(side="left")
        self.opacity_label = ttk.Label(row, text="35%", width=5, anchor="e")
        self.opacity_label.pack(side="right")
        scale = ttk.Scale(self, from_=0.0, to=1.0, variable=self.opacity,
                          command=lambda value: self._changed())
        scale.pack(fill="x", pady=(0, 4))

        for text, variable in (("Fills", self.show_fills),
                               ("Outlines", self.show_outlines),
                               ("Labels", self.show_labels)):
            ttk.Checkbutton(self, text=text, variable=variable,
                            command=self._changed).pack(anchor="w")

    def _changed(self):
        self.opacity_label.configure(text=f"{self.opacity.get() * 100:.0f}%")
        self.on_change({
            "overlay_opacity": float(self.opacity.get()),
            "show_fills": bool(self.show_fills.get()),
            "show_outlines": bool(self.show_outlines.get()),
            "show_labels": bool(self.show_labels.get()),
        })

    def set_values(self, settings):
        self.opacity.set(float(settings.get("overlay_opacity", 0.35)))
        self.show_fills.set(bool(settings.get("show_fills", True)))
        self.show_outlines.set(bool(settings.get("show_outlines", True)))
        self.show_labels.set(bool(settings.get("show_labels", True)))
        self.opacity_label.configure(text=f"{self.opacity.get() * 100:.0f}%")


class StatusBar(ttk.Frame):
    """One line, never wrapping: file on the left, measurements on the right."""

    def __init__(self, master):
        super().__init__(master, padding=(8, 3))
        self.left = ttk.Label(self, text="No image open", anchor="w")
        self.left.pack(side="left", fill="x", expand=True)
        self.right = ttk.Label(self, text="", anchor="e")
        self.right.pack(side="right")

    def set_message(self, text):
        self.left.configure(text=text)

    def set_detail(self, text):
        self.right.configure(text=text)


class ClassDialog(tk.Toplevel):
    """Create or rename a class and pick its colour."""

    def __init__(self, master, title, name="", color="#E6194B"):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self._color = color

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Name").grid(row=0, column=0, sticky="w")
        self.name_entry = ttk.Entry(body, width=28)
        self.name_entry.grid(row=0, column=1, columnspan=2, pady=4, padx=(8, 0))
        self.name_entry.insert(0, name)

        ttk.Label(body, text="Colour").grid(row=1, column=0, sticky="w")
        self.swatch = tk.Label(body, text=SWATCH * 3, fg=color, font=("Segoe UI", 12))
        self.swatch.grid(row=1, column=1, sticky="w", padx=(8, 0))
        ttk.Button(body, text="Choose...", command=self._choose).grid(row=1, column=2)

        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, columnspan=3, pady=(12, 0), sticky="e")
        ttk.Button(buttons, text="OK", width=9, command=self._ok).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", width=9, command=self.destroy).pack(side="left")

        self.bind("<Return>", lambda event: self._ok())
        self.bind("<Escape>", lambda event: self.destroy())
        self.name_entry.focus_set()
        self.grab_set()

    def _choose(self):
        chosen = colorchooser.askcolor(color=self._color, parent=self)
        if chosen and chosen[1]:
            self._color = chosen[1].upper()
            self.swatch.configure(fg=self._color)

    def _ok(self):
        name = self.name_entry.get().strip()
        if not name:
            return
        self.result = (name, self._color)
        self.destroy()
