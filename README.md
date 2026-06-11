# SkyCut D24 Inkscape Extensions (Linux / Wi-Fi)

These Inkscape extensions send cutting jobs directly to a **SkyCut D24** plotter over **Wi-Fi (WLAN)**, bypassing the original Windows-only software. They provide a fully **Linux-compatible workflow** without the proprietary tools.

> ⚠️ **Note:** I am not a programmer. I created these extensions out of necessity, due to the lack of Linux support for the SkyCut D24, with the help of AI. They currently work only over Wi-Fi. USB or wired serial connections are not supported yet. Contributions for improvements, bug fixes, or USB support are welcome.

---

## 📦 Extensions

**SkyCut D24 [v3]** — main cutting plugin
For boxes, packaging and general shapes cut with a single pressure (settings configured on the machine).

**SkyCut D24 [v3 colors]** — per-color cutting plugin
For print-and-cut labels. Each color gets its own tool, force (FS) and speed (VS), allowing kiss-cut and through-cut in a single job with one marker registration.

---

## ✨ Features

- Automatic opening of closed contours (the firmware works only with open paths)
- Knife-offset compensation with corner arcs on sharp angles
- Overcut overlap at the seam
- Smart sharp-corner vs. rounded-curve detection (based on turn concentration)
- Start point rotated onto a straight segment to hide the seam
- Nesting with island detection and route optimization (nearest-neighbor + 2-opt)
- Adjustable corner-ear sensitivity
- L-shaped registration markers (layer `Mark`)
- Per-color force/speed control for kiss-cut + through-cut in one job (colors plugin)
- Direct HP-GL output via TCP/IP (Wi-Fi)
- Built-in HTML viewer: document-oriented view, zoom/pan, progress scrubber, cut animation
- Color-based workflow: creasing (P0) and cutting (P1)
- Optional HP-GL file export for debugging
- Works on Linux, and should also work on macOS (Wi-Fi only)

---

## 🎨 Workflow

1. Create your design in a layer named **`Cut`**
2. (Optional) Place markers in a layer named **`Mark`**
3. Run **Extensions → SkyCutD24 Tools → Corner Markers**
4. Run **Extensions → SkyCutD24 Tools → SkyCut D24 [v3]** (single pressure)
   — or **SkyCut D24 [v3 colors]** for labels with per-color force/speed
5. The plotter cuts your design

---

## 🎯 Color Logic

- **Black** → Creasing (P0) → executed first
- **Other colors** → Inner cuts (P1)
- **Red** → Outer contour (P1) → executed last

In the colors plugin, four colors (black, green, yellow, red) each have an independent tool, force, speed and cutting order. Only the colors present in the document are cut.

---

## ⚙️ Requirements

- Inkscape 1.0 or newer (1.4+ recommended)
- SkyCut D24 plotter connected via **Wi-Fi (WLAN)**
- Layer names must be exactly `Cut` and `Mark`
- Python 3.x

---

## 🛠️ Installation

1. Copy the `.py` and `.inx` files to the Inkscape extensions folder:
   - **Linux:** `~/.config/inkscape/extensions/`
   - **Windows:** `%APPDATA%\Inkscape\extensions\`
   - **Mac:** `~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/`
2. Restart Inkscape
3. Run the extensions from **Extensions → SkyCutD24 Tools**

---

## 💡 Optional HP-GL Export

- Enable **"Save HP-GL"** in the extension options
- Specify a file path
- The extension saves the HP-GL commands and an HTML preview instead of sending them to the plotter

---

## 📜 License

GNU General Public License v3.0 or later

---

**Author:** Anton Kutrubiev (Bulgaria)
