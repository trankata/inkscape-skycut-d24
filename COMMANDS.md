# SkyCut D24 — HP-GL Command Reference & Adaptation Guide

This document explains the HP-GL / CMD commands the plugins send to the
plotter, and what other users need to change to adapt the tools to their setup.

> **How this was determined:** The commands below were reverse-engineered by
> generating `.plt` files from the original software with controlled
> variations (one setting changed at a time) and comparing the output, plus
> confirmed against the original software's UI and physical test cuts. They
> work on the author's **SkyCut D24**. Other models or firmware versions may
> differ. **Always test on scrap material first.**

---

## 📡 Command Reference (confirmed)

### Tools

| Command | Meaning |
|---|---|
| `P0` | Left tool (used for creasing in the author's setup) |
| `P1` | Right tool (used for cutting) |

The original software labels these "Left Tool" / "Right Tool". They are the
two physical heads of the D24.

### Force & Speed (only sent when set in software; "color mode")

| Command | Meaning |
|---|---|
| `FS<n>` | **F**orce **S**elect — cutting pressure. Valid range **0–160** (confirmed by the software's own error message). |
| `VS<n>` | **V**elocity **S**elect — cutting speed. Range **0–13**. |

**Speed mapping (confirmed from two data points):**

```
VS = cut_speed_mm_per_sec / 50
```

| Cut speed | VS |
|---|---|
| 50 mm/s | VS1 |
| 100 mm/s | VS2 |
| 200 mm/s | VS4 |
| 350 mm/s | VS7 |
| 500 mm/s | VS10 |
| 650 mm/s | VS13 (max) |

The VS range 0–13 corresponds to 0–650 mm/s, which matches the D24's maximum
cut speed.

**Travel speed** (pen-up movement speed) is **not** encoded in the HP-GL — it
is a machine setting and does not appear in the output.

### Header commands

| Command | Meaning |
|---|---|
| `IN` | Initialize / reset (HP-GL standard) |
| `PA` | Plot Absolute (HP-GL standard) |
| `FSIZE<h>,<w>` | Working-field size in plotter units. Full sheet without markers; bounding box of the job when markers are used. |
| `CMD:32,<h>,<w>,<x>,<y>` | Work area + offset. The `<x>,<y>` values change with the job's position on the sheet. |
| `CMD:18,1` | Appears only in **marker mode**. |
| `CMD:103,0` | Multi-pressure mode flag — present when different `FS` values are used in one job (per-color cutting). |
| `CMD:35,2,1,0` | Used when **no tool is explicitly assigned** (machine uses its own settings). |
| `CMD:35,1,2,0` | Used when a **tool is explicitly assigned** (P0/P1 sent). |
| `TB26,<h>,<w>` | Registration-mark setup (marker mode only). |

### Movement

| Command | Meaning |
|---|---|
| `U<x>,<y>` | Pen **U**p — travel without cutting (HP-GL standard) |
| `D<x>,<y>` | Pen **D**own — cut to point (HP-GL standard) |

### Footer

| Command | Meaning |
|---|---|
| `U0,0` | Pen up, return toward origin |
| `@ @` | End-of-job markers |

### Coordinate system

- Scale: **40 plotter units = 1 mm** (`SCALE = 40`).
- The `coord()` function maps document coordinates into the machine frame
  (rotation + mirror), derived empirically to match the machine's orientation.

---

## 🔪 Geometry behavior (matches the original software)

Confirmed by comparing the plugin's output to the original software for the
same shapes:

- **Knife offset (corner ears):** On sharp corners, a small arc of radius =
  knife offset (e.g. 0.30 mm) is added, bulging outward. The original produces
  ~7 points per ear at 0.30 mm; the plugin produces a comparable ear of the
  same size. Smooth curves get no ears.
- **Overcut:** On closed contours, cutting continues past the seam by the
  overcut distance (e.g. ~1 mm), following the contour. Both the original and
  the plugin do this the same way.
- **Circles:** Cut at their nominal radius — neither the original nor the
  plugin applies a Pythagorean radius compensation. (Negligible for normal
  sizes.)

---

## 🔧 Adapting for your setup

### 1. Connection (IP & port)
Default `192.168.0.233:8080`. Set your plotter's IP in the Connection tab.

### 2. Layer names
Paths must be in a layer named **`Cut`**; markers in a layer named **`Mark`**
(case-insensitive). Rename your layers to match.

### 3. Colors (color mode)
Default mapping: **black**→creasing (P0), **red**→outer cut (P1),
**green**/**yellow**→additional cuts. Each color has its own tool, force,
speed and order in the Colors tab.

### 4. Scale
The plugin fits the design to the page:
`scale = min(page_w / viewBox_w, page_h / viewBox_h)`. This is correct when the
Inkscape document's viewBox matches the page size (drawing directly in mm).
Files from other software (e.g. SCAL at 72 dpi) may scale differently — verify
a known dimension after import.

### 5. Knife offset & overcut
`knife_offset` (default 0.30 mm) and `overcut` (default 1.0 mm) depend on blade
and material. Thicker material generally needs more overcut.

### 6. Force / Speed ranges
Force `0–160`, speed `0–13` (= 0–650 mm/s). These match the D24. Other
machines may differ.

---

## 📋 Example job structure (two tools, marker mode)

```
IN FSIZE<h>,<w> CMD:32,...;CMD:18,1;CMD:103,0;CMD:35,1,2,0;TB26,<h>,<w>
P0;FS50;VS7;   <- creasing first (left tool, force 50, speed 350mm/s)
  U.. D.. D..  (crease lines — open paths, no overcut, no ears)
P1;FS52;VS2;   <- cutting second (right tool, force 52, speed 100mm/s)
  U.. D.. D..  (contour — with corner ears and overcut)
U0,0 @ @
```

Tools are switched by emitting `P0`/`P1` with their own `FS`/`VS` before each
block. The machine adjusts pressure and speed automatically. Cutting order is
controlled by the sequence numbers in the Colors tab.

---

## ⚠️ Disclaimer

Use at your own risk. Wrong force values or commands could damage your blade,
material, or machine. Always test on scrap first. The author is not a
programmer and built these tools with AI assistance for personal use; they are
shared as-is as a starting point for other Linux users with a SkyCut plotter.
