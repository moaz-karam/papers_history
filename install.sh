#!/usr/bin/env bash
# Install Papers History into ~/.local (or $PREFIX).
set -euo pipefail

prefix="${PREFIX:-$HOME/.local}"
app_dir="$prefix/lib/papers-history"          # application code only
launcher="$prefix/bin/papers-history"
desktop_file="$prefix/share/applications/io.github.papers_history.desktop"
icon_file="$prefix/share/icons/hicolor/scalable/apps/io.github.papers_history.svg"
# Where the app itself stores history.json — never deleted by this script.
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}/papers-history"
# Code location used by older installs, cleaned up below.
legacy_dir="$prefix/share/papers-history/papers_history"
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -rf "$app_dir" "$legacy_dir"
    rm -f "$launcher" "$desktop_file" "$icon_file"
    # Only succeeds when the folder is empty, so a history file survives.
    rmdir "$prefix/share/papers-history" 2>/dev/null || true
    echo "Removed Papers History from $prefix"
    echo "Your history is kept in $data_dir"
    exit 0
fi

if ! python3 - <<'PY'
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw  # noqa: F401
PY
then
    cat >&2 <<'MSG'
error: GTK4 and libadwaita Python bindings are required.

  Fedora:  sudo dnf install python3-gobject gtk4 libadwaita
  Ubuntu:  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
MSG
    exit 1
fi

install -d "$app_dir" "$prefix/bin"
rm -rf "$app_dir/papers_history"
cp -r "$repo_dir/papers_history" "$app_dir/papers_history"
find "$app_dir/papers_history" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -rf "$legacy_dir"

cat > "$launcher" <<'LAUNCHER'
#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib" / "papers-history"))

from papers_history.ui import main

raise SystemExit(main())
LAUNCHER
chmod 755 "$launcher"

install -Dm644 "$repo_dir/data/io.github.papers_history.desktop" "$desktop_file"
install -Dm644 "$repo_dir/data/io.github.papers_history.svg" "$icon_file"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$prefix/share/applications" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$prefix/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Installed Papers History to $prefix"
echo "Run 'papers-history' or launch it from your app grid."
