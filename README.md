# SkyCut D24 Inkscape Extension (Linux / Wi-Fi)

This Inkscape extension allows sending cutting jobs directly to a **SkyCut D24** plotter over **Wi-Fi (WLAN)**, bypassing the original Windows-only software. It provides a **Linux-compatible workflow** without requiring the proprietary software.

> ⚠️ **Note:** This extension currently works only over Wi-Fi. USB or wired serial connections are not supported yet. Contributions for improvements, bug fixes, or USB support are welcome.

---

## ✨ Features

- Automatic L-shaped registration markers (layer `Mark`)  
- Direct HP-GL output via TCP/IP (Wi-Fi)  
- Color-based workflow: creasing (P0) and cutting (P1)  
- Knife offset and overcut support  
- Optional HP-GL file export for debugging  
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

1. Copy the `.py` files to the Inkscape extensions folder:  
   - **Linux:** `~/.config/inkscape/extensions/`  
   - **Windows:** `%APPDATA%\Inkscape\extensions\`  
   - **Mac:** `~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/`  
2. Restart Inkscape  
3. Open your design and run the extension from **Extensions → SkyCutD24 Tools**

---

## 💡 Optional HP-GL Export

- If you want to check or debug the generated HP-GL file:  
  - Enable **“Save HP-GL”** in the extension options  
  - Specify a file path  
  - The extension will save the HP-GL commands instead of sending them to the plotter  

---

## 📜 License

GNU General Public License v3.0 or later  

---

**Author:** Anton Kutrubiev (Bulgaria)  
