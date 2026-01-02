# SkyCut D24 Inkscape Extension (Linux)

This extension allows you to send cutting jobs directly from **Inkscape**
to a **SkyCut D24** plotter over the network, bypassing the original
Windows-only software.

The goal of this project is to provide a **fully Linux-compatible**
workflow for SkyCut users.

---

## ✨ Features

- Automatic generation of L-shaped registration markers
- Direct HP-GL output via TCP/IP (no proprietary software required)
- Color-based workflow for creasing and cutting
- Knife offset and overcut support
- A4 / A3 media size support
- Optional HP-GL file export for debugging and comparison

---

## 🎨 Workflow

1. Create your design in a layer named **`Cut`**
2. (Optional) Create or generate markers in a layer named **`Mark`**
3. Run **Extensions → SkyCutD24 Tools → Corner Markers**
4. Run **Extensions → SkyCutD24 Tools → Send to SkyCut D24**
5. The plotter starts cutting

---

## 🎯 Color Logic

- **Black** → Creasing (P0) → executed first  
- **Other colors** → Inner cuts (P1) → executed second  
- **Red** → Outer contour (P1) → executed last  

---

## ⚙️ Requirements

- Inkscape 1.0 or newer
- SkyCut D24 connected via Wi-Fi or Ethernet
- Layer names must be exactly:
  - `Cut`
  - `Mark`

---

## ⚠️ Project Status

This project was created through experimentation and reverse engineering.
It is **experimental but functional**.

I am **not a programmer** — contributions, refactoring and improvements
are very welcome.

---

## 🤝 Contributing

Contributions, bug reports, and feature requests are welcome!  
Please use GitHub Issues or Pull Requests to contribute.

---

## 📜 License

This project is licensed under the [GNU General Public License v2.0 or later](LICENSE).

---

**Author:** Anton Kutrubiev (Bulgaria)  

Shared to enable the Linux and Inkscape community to improve and extend it.
