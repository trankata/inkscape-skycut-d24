# SkyCut D24 Inkscape Extension (Linux / Wi-Fi)

This Inkscape extension allows sending cutting jobs directly to a **SkyCut D24** plotter over **Wi-Fi (WLAN)**, bypassing the original Windows-only software. It provides a **Linux-compatible workflow** without requiring the proprietary software.

> ⚠️ **Note:** I am not a programmer. I created this extension out of necessity, due to the lack of Linux support for SkyCut D24, with the help of AI. This extension currently works only over Wi-Fi. USB or wired serial connections are not supported yet. Contributions for improvements, bug fixes, or USB support are welcome.

---

## ✨ Features

- Automatic L-shaped registration markers (layer `Mark`)
- Direct HP-GL output via TCP/IP (Wi-Fi)
- Color-based workflow: creasing (P0) and cutting (P1)
- Knife offset and overcut support
- Optional HP-GL file export for debugging
- Optional toolbar buttons for one-click access (see below)
- Works on Linux, and should also work on macOS (Wi-Fi only)

---

## 🎨 Workflow

1. Create your design in a layer named **`Cut`**
2. (Optional) Generate markers in a layer named **`Mark`**
3. Run **Extensions → SkyCutD24 Tools → Corner Markers**
4. Run **Extensions → SkyCutD24 Tools → Send to SkyCut D24**
5. The plotter cuts your design

---

## 🎯 Color Logic

- **Black** → Creasing (P0) → executed first
- **Other colors** → Inner cuts (P1) → executed second
- **Red** → Outer contour (P1) → executed last

---

## ⚙️ Requirements

- Inkscape 1.0 or newer
- SkyCut D24 plotter connected via **Wi-Fi (WLAN)**
- Layer names must be exactly `Cut` and `Mark`
- Python 3.x (for the Inkscape extension)

---

## 🛠️ Installation

1. Copy the `.py` files from the `extensions/` folder to the Inkscape extensions folder:
   - **Linux:** `~/.config/inkscape/extensions/`
   - **Windows:** `%APPDATA%\Inkscape\extensions\`
   - **Mac:** `~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/`
2. Restart Inkscape
3. Open your design and run the extension from **Extensions → SkyCutD24 Tools**

---

## 🔘 Optional: Toolbar Buttons

If you'd rather launch the tools with one click instead of digging through the
**Extensions** menu, you can add buttons directly to Inkscape's command toolbar
(the top bar with New / Open / Save).

A small installer in `toolbar-buttons-install/` automates this. It takes the
stock `toolbar-commands.ui` from your machine, injects the buttons into it, and
installs the matching icons — so it keeps working across Inkscape versions
instead of shipping a fixed toolbar file.

### Install

```bash
cd toolbar-buttons-install
python3 install_buttons.py
```

Then **fully restart Inkscape** (close all windows). Two buttons appear at the
right end of the command toolbar: **SkyCut** and **Corner Markers**.

### Quick install from a clone

If you don't keep the repo locally, you can clone it, run the installer, and
delete the clone afterwards. The installer copies everything it needs into your
user profile (`~/.config/inkscape` and `~/.local/share/icons`), so the clone is
not required to stay:

```bash
git clone https://github.com/trankata/inkscape-skycut-d24.git
cd inkscape-skycut-d24/toolbar-buttons-install
python3 install_buttons.py
cd ../..
rm -rf inkscape-skycut-d24
```

Then **fully restart Inkscape**.

> ℹ️ This only sets up the toolbar buttons. The buttons are shortcuts to the
> extensions, so make sure the extensions themselves are installed first (see
> [Installation](#️-installation)). If you delete the clone, copy the extension
> files before removing it.

### Options

```bash
python3 install_buttons.py --reset      # rebuild from a clean toolbar, then inject
python3 install_buttons.py --uninstall  # remove the buttons and icons again
```

Re-running the plain install is safe — existing buttons are detected and skipped.
Use `--reset` if your toolbar ever gets out of sync (for example after upgrading
Inkscape, or if a button was added twice).

### Customizing / adding more buttons

Open `install_buttons.py` and edit the `BUTTONS` list near the top. Each entry
needs the action name (the **ID** shown in *Edit → Preferences → Interface →
Keyboard*), an icon name, a label and a tooltip:

```python
{
    "id":        "skycut_btn",
    "action":    "app.skycut.send.to.d24.v5.eng",
    "icon":      "skycut-cut",
    "icon_file": "skycut-cut.svg",
    "label":     "SkyCut",
    "tooltip":   "Open the SkyCut D24 plugin",
},
```

Put the matching SVG icon in `toolbar-buttons-install/icons/`. Icons should be a
clean 16×16 SVG (square, `viewBox="0 0 16 16"`, visible color).

> ⚠️ **Icon names must be unique.** A generic `icon-name` such as `markers`
> collides with a built-in Inkscape icon and the built-in one wins, so your icon
> won't show. Always prefix it, e.g. `skycut-…` or `corner-…`.

---

## 💡 Optional HP-GL Export

- If you want to check or debug the generated HP-GL file:
  - Enable **"Save HP-GL"** in the extension options
  - Specify a file path
  - The extension will save the HP-GL commands instead of sending them to the plotter

---

## 📜 License

GNU General Public License v3.0 or later

---

**Author:** Anton Kutrubiev (Bulgaria)
