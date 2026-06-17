#!/usr/bin/env python3
"""
install_buttons.py — add custom toolbar buttons + icons to Inkscape's command bar.

What it does:
  * Takes Inkscape's stock toolbar-commands.ui (found on THIS machine) and copies
    it into your user profile the first time, then injects one button per entry in
    BUTTONS below. Idempotent: re-running won't duplicate buttons.
  * Copies the matching SVG icons from ./icons into your user icon theme
    (~/.local/share/icons/hicolor/scalable/actions) and refreshes the icon cache.

Usage:
  python3 install_buttons.py             # install / update
  python3 install_buttons.py --reset     # re-copy a pristine toolbar first, then inject
  python3 install_buttons.py --uninstall # remove the buttons + icons this script added
  optional: --data-dir /path/to/share/inkscape   --config-dir /path/to/profile/inkscape

After running, FULLY restart Inkscape (close all windows).

IMPORTANT — icon names must be unique:
  Each button's `icon` (the GtkImage icon-name) must NOT collide with a built-in
  Inkscape icon. A bare name like "markers" loses to the built-in one, so prefix it
  (e.g. "skycut-...", "corner-..."). The matching file in ./icons must be
  <icon>.svg and should be a clean 16x16 SVG (square, viewBox="0 0 16 16",
  visible color).
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

# ----------------------------------------------------------------------
# CONFIG — define your buttons here. Add more dicts to add more buttons.
# ----------------------------------------------------------------------
BUTTONS = [
    {
        "id":        "skycut_btn",
        "action":    "app.skycut.send.to.d24.v5.eng",  # use the .noprefs variant to run without dialog
        "icon":      "skycut-cut",            # GtkImage icon-name (no .svg)
        "icon_file": "skycut-cut.svg",        # file inside ./icons
        "label":     "SkyCut",
        "tooltip":   "Open the SkyCut D24 plugin",
    },
    {
        "id":        "corner_markers_btn",
        "action":    "app.corner.markers.bg",
        "icon":      "corner-markers-bg",
        "icon_file": "corner-markers-bg.svg",
        "label":     "Corner Markers",
        "tooltip":   "Add corner markers",
    },
]

TOOLBAR_FILE = "toolbar-commands.ui"
REPO_ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
# ----------------------------------------------------------------------


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except Exception:
        return None


def system_data_dir():
    """Locate Inkscape's stock data directory (.../share/inkscape)."""
    res = run(["inkscape", "--system-data-directory"])
    if res and res.returncode == 0:
        d = res.stdout.strip()
        if d and os.path.isdir(d):
            return d
    for d in (
        "/usr/share/inkscape",
        "/usr/local/share/inkscape",
        "/var/lib/flatpak/app/org.inkscape.Inkscape/current/active/files/share/inkscape",
        os.path.expanduser(
            "~/.local/share/flatpak/app/org.inkscape.Inkscape/current/active/files/share/inkscape"
        ),
    ):
        if os.path.isdir(d):
            return d
    return None


def user_config_dir():
    """Locate your Inkscape user profile (.../inkscape)."""
    env = os.environ.get("INKSCAPE_PROFILE_DIR")
    if env:
        return os.path.expanduser(env)
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    candidates = [os.path.join(xdg, "inkscape")]
    candidates += glob.glob(os.path.expanduser("~/snap/inkscape/*/.config/inkscape"))
    candidates.append(os.path.expanduser("~/.var/app/org.inkscape.Inkscape/config/inkscape"))
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]  # default; will be created if missing


def icons_dir():
    xdg_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(xdg_data, "icons", "hicolor", "scalable", "actions")


def make_block(btn, position):
    return (
        '    <child>\n'
        '      <object class="GtkButton" id="%(id)s">\n'
        '        <property name="visible">True</property>\n'
        '        <property name="can-focus">True</property>\n'
        '        <property name="receives-default">True</property>\n'
        '        <property name="action-name">%(action)s</property>\n'
        '        <property name="tooltip-text" translatable="yes">%(tooltip)s</property>\n'
        '        <child>\n'
        '          <object class="GtkImage">\n'
        '            <property name="visible">True</property>\n'
        '            <property name="can-focus">False</property>\n'
        '            <property name="icon-name">%(icon)s</property>\n'
        '          </object>\n'
        '        </child>\n'
        '      </object>\n'
        '      <packing>\n'
        '        <property name="expand">False</property>\n'
        '        <property name="fill">True</property>\n'
        '        <property name="position">%(pos)d</property>\n'
        '      </packing>\n'
        '    </child>\n'
        % {
            "id": btn["id"],
            "action": btn["action"],
            "tooltip": btn["tooltip"],
            "icon": btn["icon"],
            "pos": position,
        }
    )


def next_position(content):
    nums = [int(x) for x in re.findall(
        r'<property name="position">(\d+)</property>', content)]
    return (max(nums) + 1) if nums else 0


def inject(content, btn):
    """Insert a button block just before the toolbar's <style> section."""
    if 'id="%s"' % btn["id"] in content:
        return content, False
    pos = next_position(content)
    block = make_block(btn, pos)
    idx = content.rfind("<style>")
    if idx == -1:                       # very defensive fallback
        idx = content.rfind("</object>")
    line_start = content.rfind("\n", 0, idx) + 1
    return content[:line_start] + block + content[line_start:], True


def find_child_block(content, btn_id):
    """Return (start, end) slice of the <child> block wrapping a given button id."""
    m = re.search(r'<object class="GtkButton" id="%s">' % re.escape(btn_id), content)
    if not m:
        return None
    start = content.rfind("<child>", 0, m.start())
    if start == -1:
        return None
    line_start = content.rfind("\n", 0, start) + 1
    depth = 0
    for tm in re.finditer(r'<child>|</child>', content[start:]):
        depth += 1 if tm.group() == "<child>" else -1
        if depth == 0:
            end = start + tm.end()
            if content[end:end + 1] == "\n":
                end += 1
            return (line_start, end)
    return None


def ensure_base_toolbar(user_ui, reset):
    dst = os.path.join(user_ui, TOOLBAR_FILE)
    if os.path.exists(dst) and not reset:
        return dst
    sysdir = system_data_dir()
    if not sysdir:
        sys.exit("ERROR: could not locate Inkscape's data directory.\n"
                 "       Re-run with --data-dir /path/to/share/inkscape")
    src = os.path.join(sysdir, "ui", TOOLBAR_FILE)
    if not os.path.isfile(src):
        sys.exit("ERROR: stock %s not found at %s" % (TOOLBAR_FILE, src))
    os.makedirs(user_ui, exist_ok=True)
    shutil.copy2(src, dst)
    print("  base toolbar copied from %s" % src)
    return dst


def update_cache():
    base = os.path.dirname(os.path.dirname(icons_dir()))  # .../hicolor
    if shutil.which("gtk-update-icon-cache"):
        run(["gtk-update-icon-cache", "-f", "-t", base])
        print("  icon cache refreshed")


def do_install(reset):
    user_ui = os.path.join(user_config_dir(), "ui")
    toolbar = ensure_base_toolbar(user_ui, reset)

    content = open(toolbar, encoding="utf-8").read()
    changed = False
    for btn in BUTTONS:
        content, added = inject(content, btn)
        print(("+ added button:   " if added else "  already present: ") + btn["label"])
        changed = changed or added
    if changed:
        open(toolbar, "w", encoding="utf-8").write(content)

    tgt = icons_dir()
    os.makedirs(tgt, exist_ok=True)
    for btn in BUTTONS:
        src = os.path.join(REPO_ICONS_DIR, btn["icon_file"])
        if not os.path.isfile(src):
            print("! missing icon in repo: %s" % src)
            continue
        shutil.copy2(src, os.path.join(tgt, btn["icon_file"]))
        print("+ installed icon: %s" % btn["icon_file"])
    update_cache()
    print("\nDone. Fully restart Inkscape to see the buttons.")


def do_uninstall():
    toolbar = os.path.join(user_config_dir(), "ui", TOOLBAR_FILE)
    if os.path.isfile(toolbar):
        content = open(toolbar, encoding="utf-8").read()
        for btn in BUTTONS:
            blk = find_child_block(content, btn["id"])
            if blk:
                content = content[:blk[0]] + content[blk[1]:]
                print("- removed button: %s" % btn["label"])
        open(toolbar, "w", encoding="utf-8").write(content)
    tgt = icons_dir()
    for btn in BUTTONS:
        p = os.path.join(tgt, btn["icon_file"])
        if os.path.isfile(p):
            os.remove(p)
            print("- removed icon:   %s" % btn["icon_file"])
    update_cache()
    print("\nDone. Fully restart Inkscape.")


def main():
    ap = argparse.ArgumentParser(description="Install SkyCut toolbar buttons + icons.")
    ap.add_argument("--reset", action="store_true",
                    help="re-copy a pristine toolbar-commands.ui before injecting")
    ap.add_argument("--uninstall", action="store_true",
                    help="remove the buttons and icons this script installed")
    ap.add_argument("--data-dir", help="override Inkscape data dir (.../share/inkscape)")
    ap.add_argument("--config-dir", help="override Inkscape user profile dir (.../inkscape)")
    args = ap.parse_args()

    if args.config_dir:
        os.environ["INKSCAPE_PROFILE_DIR"] = args.config_dir
    if args.data_dir:
        _d = args.data_dir
        global system_data_dir
        system_data_dir = lambda: _d if os.path.isdir(_d) else None

    do_uninstall() if args.uninstall else do_install(args.reset)


if __name__ == "__main__":
    main()
