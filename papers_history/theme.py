"""Dark-blue visual theme.

Colours are injected as GTK named colours so every libadwaita widget follows
along, then a handful of app-specific rules handle the paper rows.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

CSS = """
/* ---------- palette ---------------------------------------------------- */
@define-color accent_bg_color #2f74e0;
@define-color accent_color #8ab6ff;
@define-color accent_fg_color #ffffff;

@define-color window_bg_color #0a1524;
@define-color window_fg_color #e4eefb;
@define-color view_bg_color #0a1524;
@define-color view_fg_color #e4eefb;

@define-color headerbar_bg_color #0c1a2d;
@define-color headerbar_fg_color #e4eefb;
@define-color headerbar_border_color #16283f;

@define-color card_bg_color #0f2137;
@define-color card_fg_color #e4eefb;
@define-color dialog_bg_color #0c1a2d;
@define-color popover_bg_color #10243c;
@define-color popover_fg_color #e4eefb;
@define-color borders #1b3352;

/* ---------- window chrome --------------------------------------------- */
window.papers-window,
window.papers-window .background {
  background-color: @window_bg_color;
}

.papers-header {
  background-color: @headerbar_bg_color;
  box-shadow: inset 0 -1px @headerbar_border_color;
}

.papers-header windowtitle {
  font-weight: bold;
}

.papers-searchbar {
  background-color: @headerbar_bg_color;
  padding: 2px 14px 12px 14px;
}

.papers-sort {
  font-size: 0.9em;
}

/* ---------- list ------------------------------------------------------- */
.papers-list {
  background-color: transparent;
}

.papers-list > row {
  background-color: transparent;
  border-radius: 12px;
  margin: 2px 12px;
  padding: 11px 12px;
  transition: background-color 120ms ease-out;
}

.papers-list > row:hover {
  background-color: rgba(74, 144, 255, 0.10);
}

.papers-list > row:selected {
  background-color: rgba(58, 124, 226, 0.28);
}

.papers-list > row:selected:hover {
  background-color: rgba(58, 124, 226, 0.36);
}

.papers-list > row:focus {
  outline: none;
}

/* ---------- row typography -------------------------------------------- */
.paper-title {
  font-size: 1.22em;
  font-weight: bold;
  color: #eaf3ff;
}

.paper-path {
  font-size: 0.82em;
  color: #8aa8c9;
}

.paper-date {
  font-size: 0.8em;
  color: #9fbbd9;
}

.paper-meta {
  font-size: 0.74em;
  color: #6f8dae;
}

.paper-icon {
  color: #5b9dff;
}

.paper-row-missing .paper-title {
  color: #aabdd2;
}

.paper-row-missing .paper-icon {
  color: #d9a53c;
}

.paper-missing-note {
  font-size: 0.74em;
  color: #f0b95a;
  font-weight: bold;
}

/* ---------- misc ------------------------------------------------------- */
toast {
  background-color: #16345a;
  color: #eaf3ff;
}

scrolledwindow.papers-scroll {
  background-color: transparent;
}

window.papers-window statuspage image {
  color: #4d86d6;
}
"""


def install() -> None:
    """Force the dark blue colour scheme for this application."""
    style_manager = Adw.StyleManager.get_default()
    style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

    display = Gdk.Display.get_default()
    if display is None:  # pragma: no cover - only without a compositor
        return

    provider = Gtk.CssProvider()
    try:
        provider.load_from_string(CSS)
    except AttributeError:  # pragma: no cover - GTK < 4.12
        provider.load_from_data(CSS.encode("utf-8"))

    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
    )
