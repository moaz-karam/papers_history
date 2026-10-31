"""GTK4 / libadwaita user interface for Papers History."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import APP_ID, APP_NAME, __version__, theme, util  # noqa: E402
from .store import Entry, HistoryStore  # noqa: E402

SORT_KEYS = ("recent", "name", "file", "added")
SORT_LABELS = ("Recent", "Name", "File date", "Added")


class PaperRow(Gtk.ListBoxRow):
    """One history entry: big file name, small path, small date."""

    def __init__(self, entry: Entry, now: float | None = None) -> None:
        super().__init__()
        self.entry = entry
        self.add_css_class("paper-row")

        missing = not entry.exists
        if missing:
            self.add_css_class("paper-row-missing")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        box.set_hexpand(True)

        icon = Gtk.Image.new_from_icon_name(
            "dialog-warning-symbolic" if missing else "x-office-document-symbolic"
        )
        icon.set_pixel_size(26)
        icon.set_valign(Gtk.Align.CENTER)
        icon.add_css_class("paper-icon")

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)

        title = Gtk.Label(
            label=entry.title,
            xalign=0.0,
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=70,
            hexpand=True,
        )
        title.add_css_class("paper-title")

        folder = Gtk.Label(
            label=util.tilde(entry.directory),
            xalign=0.0,
            ellipsize=Pango.EllipsizeMode.MIDDLE,
            max_width_chars=90,
            hexpand=True,
        )
        folder.add_css_class("paper-path")

        text.append(title)
        text.append(folder)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        side.set_valign(Gtk.Align.CENTER)
        side.set_halign(Gtk.Align.END)

        date = Gtk.Label(label=util.humanize_time(entry.activity, now), xalign=1.0)
        date.add_css_class("paper-date")
        side.append(date)

        meta_text = util.format_meta(entry)
        if meta_text:
            meta = Gtk.Label(label=meta_text, xalign=1.0)
            meta.add_css_class("paper-missing-note" if missing else "paper-meta")
            side.append(meta)

        box.append(icon)
        box.append(text)
        box.append(side)
        self.set_child(box)
        self.set_tooltip_text(entry.path)


class PapersWindow(Adw.ApplicationWindow):
    def __init__(self, store: HistoryStore, **kwargs) -> None:
        super().__init__(**kwargs)
        self.store = store
        self._query = ""
        self._entries: list[Entry] = []
        self._file_dialog: Gtk.FileDialog | None = None

        self.set_title(APP_NAME)
        self.set_default_size(960, 720)
        self.set_size_request(560, 400)
        self.add_css_class("papers-window")

        self._build_actions()
        self._build_ui()
        self._setup_dnd()
        self.refresh()

    # -- construction ------------------------------------------------------

    def _build_ui(self) -> None:
        self.title_widget = Adw.WindowTitle(title=APP_NAME, subtitle="")

        header = Adw.HeaderBar()
        header.add_css_class("papers-header")
        header.set_title_widget(self.title_widget)

        self.sort_dropdown = Gtk.DropDown.new_from_strings(list(SORT_LABELS))
        self.sort_dropdown.set_tooltip_text("Sort papers by date or name")
        self.sort_dropdown.add_css_class("papers-sort")
        self.sort_dropdown.connect("notify::selected", self._on_sort_changed)
        header.pack_start(self.sort_dropdown)

        self.search_button = Gtk.ToggleButton(
            icon_name="system-search-symbolic", tooltip_text="Search (Ctrl+F)"
        )
        self.search_button.connect("toggled", self._on_search_toggled)

        open_button = Gtk.Button(label="Open PDF", tooltip_text="Add a PDF (Ctrl+O)")
        open_button.add_css_class("suggested-action")
        open_button.set_action_name("win.open")

        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic", tooltip_text="Main menu"
        )
        menu_button.set_menu_model(self._build_menu())

        # pack_end inserts to the left of previously packed widgets.
        header.pack_end(menu_button)
        header.pack_end(open_button)
        header.pack_end(self.search_button)

        self.search_entry = Gtk.SearchEntry(
            placeholder_text="Search by file name or path…"
        )
        self.search_entry.set_hexpand(True)
        if hasattr(self.search_entry, "set_search_delay"):
            # Filter a 200-row list instantly instead of waiting 150 ms.
            self.search_entry.set_search_delay(0)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("stop-search", self._on_stop_search)

        self.search_bar = Gtk.SearchBar()
        self.search_bar.add_css_class("papers-searchbar")
        self.search_bar.set_child(self.search_entry)
        self.search_bar.set_show_close_button(True)
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.connect("notify::search-mode-enabled", self._on_search_mode)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self.search_bar)

        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("papers-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect("row-activated", self._on_row_activated)
        self._install_list_input()

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.add_css_class("papers-scroll")
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_vexpand(True)
        self.scroller.set_child(self.listbox)
        self.scroller.set_margin_top(6)
        self.scroller.set_margin_bottom(6)

        empty_page = Adw.StatusPage(
            icon_name="folder-documents-symbolic",
            title="No papers yet",
            description=(
                "Open a PDF and it will show up here, ready to search. "
                f"The {self.store.max_entries} most recent papers are kept."
            ),
        )
        empty_button = Gtk.Button(label="Open a PDF…")
        empty_button.add_css_class("suggested-action")
        empty_button.add_css_class("pill")
        empty_button.set_halign(Gtk.Align.CENTER)
        empty_button.set_action_name("win.open")
        empty_page.set_child(empty_button)

        self.no_results_page = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title="No results",
            description="Try a different search.",
        )

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        self.stack.add_named(self.scroller, "list")
        self.stack.add_named(empty_page, "empty")
        self.stack.add_named(self.no_results_page, "no-results")

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(self.stack)

        toolbar.set_content(self.toasts)
        self.set_content(toolbar)

        self.row_menu = Gtk.PopoverMenu.new_from_model(self._build_row_menu())
        self.row_menu.connect("closed", lambda popover: popover.unparent())

    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append("Open PDF…", "win.open")
        menu.append("Refresh history", "win.refresh")

        history_section = Gio.Menu()
        history_section.append("Clear history…", "win.clear-history")
        history_section.append("Open data folder", "win.open-data-folder")
        menu.append_section(None, history_section)

        app_section = Gio.Menu()
        app_section.append("About Papers History", "app.about")
        app_section.append("Quit", "app.quit")
        menu.append_section(None, app_section)
        return menu

    def _build_row_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append("Open in Papers", "win.open-selected")
        menu.append("Open containing folder", "win.open-folder")
        menu.append("Copy path", "win.copy-path")

        section = Gio.Menu()
        section.append("Remove from history", "win.remove-selected")
        menu.append_section(None, section)
        return menu

    def _build_actions(self) -> None:
        actions = {
            "open": self._on_open_clicked,
            "open-selected": lambda *_: self._open_selected(),
            "open-folder": lambda *_: self._open_selected_folder(),
            "copy-path": lambda *_: self._copy_selected_path(),
            "remove-selected": lambda *_: self._remove_selected(),
            "clear-history": self._on_clear_history,
            "open-data-folder": lambda *_: util.open_folder(self.store.path.parent),
            "refresh": lambda *_: self.refresh(),
            "search": lambda *_: self._focus_search(),
        }
        for name, handler in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    def _install_list_input(self) -> None:
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_list_key)
        self.listbox.add_controller(keys)

        right_click = Gtk.GestureClick(button=3)
        right_click.connect("pressed", self._on_right_click)
        self.listbox.add_controller(right_click)

    def _setup_dnd(self) -> None:
        try:
            target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        except (TypeError, AttributeError):  # pragma: no cover - defensive
            return
        target.connect("drop", self._on_drop)
        self.add_controller(target)

    # -- data --------------------------------------------------------------

    def refresh(self, select: str | None = None) -> None:
        if select is None:
            row = self.listbox.get_selected_row()
            select = row.entry.path if isinstance(row, PaperRow) else None

        adjustment = self.scroller.get_vadjustment()
        scroll_offset = adjustment.get_value() if adjustment else 0.0

        entries = self.store.entries()
        self._entries = entries

        terms = [term for term in self._query.casefold().split() if term]
        visible = [
            entry for entry in entries if all(_matches(entry, term) for term in terms)
        ]
        visible = self._sorted(visible)

        child = self.listbox.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.listbox.remove(child)
            child = following

        selected_row = None
        for entry in visible:
            row = PaperRow(entry)
            self.listbox.append(row)
            if select and entry.path == select:
                selected_row = row

        if selected_row is not None:
            self.listbox.select_row(selected_row)

        if adjustment is not None:
            adjustment.set_value(scroll_offset)

        self._update_status(len(entries), len(visible), bool(terms))

    def _sorted(self, entries: list[Entry]) -> list[Entry]:
        index = max(0, self.sort_dropdown.get_selected())
        key = SORT_KEYS[index]
        if key == "name":
            return sorted(entries, key=lambda entry: entry.title.casefold())
        if key == "file":
            return sorted(entries, key=lambda entry: entry.mtime, reverse=True)
        if key == "added":
            return sorted(entries, key=lambda entry: entry.added, reverse=True)
        return sorted(entries, key=lambda entry: entry.activity, reverse=True)

    def _update_status(self, total: int, shown: int, filtered: bool) -> None:
        limit = self.store.max_entries
        if filtered:
            subtitle = f"{shown} of {total} papers · limit {limit}"
            self.no_results_page.set_description(
                f"Nothing matches “{GLib.markup_escape_text(self._query.strip())}”."
            )
        elif total == 0:
            subtitle = f"Recent PDFs · limit {limit}"
        else:
            subtitle = f"{total} papers · limit {limit}"
        self.title_widget.set_subtitle(subtitle)

        if total == 0:
            self.stack.set_visible_child_name("empty")
        elif shown == 0:
            self.stack.set_visible_child_name("no-results")
        else:
            self.stack.set_visible_child_name("list")

    # -- opening -----------------------------------------------------------

    def open_many(self, paths) -> None:
        """Open PDFs in Papers and record them in the history."""
        opened: list[str] = []
        for raw in paths:
            path = Path(raw).expanduser()
            if not path.is_file():
                self._info("File not found", f"{util.tilde(str(path))} does not exist.")
                continue
            try:
                util.launch_viewer(path)
            except util.ViewerNotFound as error:
                self._info("PDF viewer not found", str(error))
                return
            entry = self.store.add(path, opened=True)
            opened.append(entry.path)

        if opened:
            self.refresh(select=opened[-1])
            self.toasts.add_toast(Adw.Toast.new(f"Opened {Path(opened[-1]).name}"))

    def _open_entry(self, entry: Entry) -> None:
        path = Path(entry.path)
        if not path.is_file():
            self._confirm(
                "File not found",
                f"{util.tilde(entry.path)}\n\nThis file is no longer on disk. "
                "Remove it from your history?",
                "Remove",
                on_confirm=lambda: self._remove_path(entry.path),
            )
            return
        try:
            util.launch_viewer(path)
        except util.ViewerNotFound as error:
            self._info("PDF viewer not found", str(error))
            return
        stored = self.store.add(path, opened=True)
        self.refresh(select=stored.path)
        self.toasts.add_toast(Adw.Toast.new(f"Opened {path.name}"))

    def _add_paths(self, paths) -> None:
        added = 0
        for raw in paths:
            path = Path(raw)
            if path.suffix.lower() != ".pdf" or not path.is_file():
                continue
            self.store.add(path)
            added += 1
        if added:
            self.refresh()
            label = "paper" if added == 1 else "papers"
            self.toasts.add_toast(Adw.Toast.new(f"Added {added} {label}"))

    # -- callbacks ---------------------------------------------------------

    def _on_row_activated(self, _listbox, row) -> None:
        if isinstance(row, PaperRow):
            self._open_entry(row.entry)

    def _on_list_key(self, _controller, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Delete:
            self._remove_selected()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._open_selected()
            return True
        return False

    def _on_right_click(self, _gesture, _n_press, x, y) -> None:
        row = self.listbox.get_row_at_y(int(y))
        if row is None:
            return
        self.listbox.select_row(row)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        if self.row_menu.get_parent() is not None:
            self.row_menu.unparent()
        self.row_menu.set_parent(self.listbox)
        self.row_menu.set_pointing_to(rect)
        self.row_menu.popup()

    def _on_open_clicked(self, *_args) -> None:
        if self._file_dialog is None:
            dialog = Gtk.FileDialog(title="Open PDF", modal=True)
            pdf_filter = Gtk.FileFilter(name="PDF documents")
            pdf_filter.add_mime_type("application/pdf")
            pdf_filter.add_pattern("*.pdf")
            pdf_filter.add_pattern("*.PDF")
            any_filter = Gtk.FileFilter(name="All files")
            any_filter.add_pattern("*")

            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(pdf_filter)
            filters.append(any_filter)
            dialog.set_filters(filters)
            dialog.set_default_filter(pdf_filter)
            self._file_dialog = dialog

        self._file_dialog.open(self, None, self._on_file_chosen)

    def _on_file_chosen(self, dialog, result) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path() if gfile else None
        if path:
            self.open_many([path])

    def _on_drop(self, _target, value, _x, _y) -> bool:
        files = value.get_files() if hasattr(value, "get_files") else []
        self._add_paths([item.get_path() for item in files if item.get_path()])
        return True

    def _on_sort_changed(self, _dropdown, _pspec) -> None:
        self.refresh()

    def _on_search_changed(self, entry) -> None:
        self._query = entry.get_text()
        self.refresh()

    def _on_search_toggled(self, button) -> None:
        active = button.get_active()
        self.search_bar.set_search_mode(active)
        if active:
            self.search_entry.grab_focus()
        elif self._query:
            self.search_entry.set_text("")

    def _on_search_mode(self, bar, _pspec) -> None:
        active = bar.get_search_mode()
        if self.search_button.get_active() != active:
            self.search_button.set_active(active)
        if not active and self._query:
            self.search_entry.set_text("")

    def _on_stop_search(self, _entry) -> None:
        self.search_button.set_active(False)

    def _on_clear_history(self, *_args) -> None:
        if not self._entries:
            return
        self._confirm(
            "Clear history?",
            f"This removes all {len(self._entries)} saved papers from the list. "
            "The PDF files themselves are not deleted.",
            "Clear history",
            destructive=True,
            on_confirm=self._clear_history,
        )

    # -- helpers -----------------------------------------------------------

    def _clear_history(self) -> None:
        self.store.clear()
        self.refresh()
        self.toasts.add_toast(Adw.Toast.new("History cleared"))

    def _focus_search(self) -> None:
        self.search_button.set_active(True)
        self.search_bar.set_search_mode(True)
        self.search_entry.grab_focus()

    def _selected_entry(self) -> Entry | None:
        row = self.listbox.get_selected_row()
        return row.entry if isinstance(row, PaperRow) else None

    def _open_selected(self) -> None:
        entry = self._selected_entry()
        if entry is not None:
            self._open_entry(entry)

    def _open_selected_folder(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        try:
            util.open_folder(entry.directory)
        except Exception as error:  # pragma: no cover - desktop specific
            self._info("Could not open folder", str(error))

    def _copy_selected_path(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(entry.path)
        self.toasts.add_toast(Adw.Toast.new("Path copied"))

    def _remove_selected(self) -> None:
        entry = self._selected_entry()
        if entry is not None:
            self._remove_path(entry.path)

    def _remove_path(self, path: str) -> None:
        if self.store.remove(path):
            self.refresh()
            self.toasts.add_toast(Adw.Toast.new("Removed from history"))

    def _info(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("close", "OK")
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.present(self)

    def _confirm(self, heading, body, confirm_label, on_confirm, destructive=False):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", confirm_label)
        dialog.set_default_response("confirm")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance(
            "confirm",
            (
                Adw.ResponseAppearance.DESTRUCTIVE
                if destructive
                else Adw.ResponseAppearance.SUGGESTED
            ),
        )
        dialog.connect(
            "response",
            lambda _dialog, response: on_confirm() if response == "confirm" else None,
        )
        dialog.present(self)


def _matches(entry: Entry, term: str) -> bool:
    return term in entry.title.casefold() or term in entry.path.casefold()


class PapersHistoryApp(Adw.Application):
    def __init__(self, store: HistoryStore | None = None) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.store = store or HistoryStore()
        self.pending_files: list[Path] = []
        self.window: PapersWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        theme.install()
        self._install_accels()
        self._install_app_actions()

    def do_activate(self) -> None:
        if self.window is None:
            self.window = PapersWindow(application=self, store=self.store)
            self.window.connect("close-request", self._on_close_request)

        pending, self.pending_files = self.pending_files, []
        self.window.present()

        if pending:
            self.window.open_many(pending)

    def _on_close_request(self, _window) -> bool:
        self.window = None
        return False

    def _install_accels(self) -> None:
        self.set_accels_for_action("win.open", ["<Control>o"])
        self.set_accels_for_action("win.search", ["<Control>f"])
        self.set_accels_for_action("win.refresh", ["F5"])
        self.set_accels_for_action("app.about", ["F1"])
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def _install_app_actions(self) -> None:
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

    def _on_about(self, *_args) -> None:
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=__version__,
            developer_name="Papers History contributors",
            comments=(
                "A searchable history of your recent PDFs. Papers is launched "
                "from each document's own folder."
            ),
            license_type=Gtk.License.MIT_X11,
        )
        dialog.present(self.window)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)

    if "--version" in args:
        print(f"papers-history {__version__}")
        return 0
    if "--help" in args or "-h" in args:
        print(
            "Usage: papers-history [PDF…]\n\n"
            "A searchable history for the Papers PDF viewer. Any PDFs given on\n"
            "the command line are opened in Papers and added to the history.\n\n"
            f"Environment: {util.VIEWER_ENV} overrides the viewer binary "
            f"(default: {util.DEFAULT_VIEWER})."
        )
        return 0

    app = PapersHistoryApp()
    app.pending_files = [
        Path(arg).expanduser()
        for arg in args[1:]
        if not arg.startswith("-") and Path(arg).expanduser().suffix.lower() == ".pdf"
    ]
    return app.run(args)
