# SkyCut D24 Inkscape Extension (Linux)

This Inkscape extension allows sending cutting jobs directly to a **SkyCut D24** plotter
over the network, bypassing the original Windows-only software. It provides a **Linux-compatible workflow**.

> ⚠️ **Note:** I am not a programmer. I created this extension out of necessity for Linux,
> with the help of AI. Contributions, improvements, and bug fixes are very welcome.

---

## ✨ Features

- Automatic L-shaped registration markers
- Direct HP-GL output via TCP/IP (no proprietary software required)
- Color-based workflow for creasing (P0) and cutting (P1)
- Knife offset and overcut support
- A4 / A3 media size support
- Optional HP-GL file export for debugging

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
- SkyCut D24 connected via Wi-Fi or Ethernet  
- Layer names must be exactly `Cut` and `Mark`  

---

## 📜 License

GNU General Public License v3.0 or later

---

**Author:** Anton Kutrubiev (Bulgaria)  
