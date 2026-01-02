#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Corner Markers (L-shaped) – Inkscape extension
#

import inkex
from inkex import PathElement, Layer, Style, Transform, Group


class CornerMarkers(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--offset_mm", type=float, default=5.0)

    def effect(self):
        svg = self.svg
        selection = svg.selection

        if not selection:
            inkex.errormsg("No objects selected")
            return

        # =========================================================
        # APPLY TRANSFORMS (ИСТИНСКО!)
        # =========================================================
        for el in selection.values():
            self._apply_recursive(el)

        # ---------- PARAMETERS ----------
        offset = svg.unittouu(f"{self.options.offset_mm}mm")
        arm = svg.unittouu("15mm")
        stroke = svg.unittouu("1mm")

        # ---------- BOUNDING BOX ----------
        bboxes = [el.bounding_box() for el in selection.values()]
        minx = min(b.left for b in bboxes) - offset
        maxx = max(b.right for b in bboxes) + offset
        miny = min(b.top for b in bboxes) - offset
        maxy = max(b.bottom for b in bboxes) + offset

        # ---------- Mark LAYER ----------
        mark_layer = None
        for layer in svg.xpath("//svg:g[@inkscape:groupmode='layer']"):
            if layer.label == "Mark":
                mark_layer = layer
                break

        if mark_layer is None:
            mark_layer = Layer.new("Mark")
            svg.add(mark_layer)

        # 🔒 LOCK MARK LAYER
        mark_layer.set("sodipodi:insensitive", "true")

        style = Style({
            "stroke": "#000000",
            "stroke-width": stroke,
            "fill": "none",
            "stroke-linecap": "square"
        })

        # ---------- 4 L-SHAPED MARKERS ----------
        corners = [
            [(minx, miny + arm), (minx, miny), (minx + arm, miny)],
            [(maxx - arm, miny), (maxx, miny), (maxx, miny + arm)],
            [(maxx, maxy - arm), (maxx, maxy), (maxx - arm, maxy)],
            [(minx + arm, maxy), (minx, maxy), (minx, maxy - arm)],
        ]

        for pts in corners:
            path = PathElement()
            path.path = inkex.Path([
                ('M', pts[0]),
                ('L', pts[1]),
                ('L', pts[2])
            ])
            path.style = style
            mark_layer.add(path)

    # =========================================================
    # APPLY TRANSFORM RECURSIVELY (ПРАВИЛНО)
    # =========================================================
    def _apply_recursive(self, el):
        # Ако е група с transform → изпичаме го в децата
        if isinstance(el, Group) and el.transform:
            t = el.transform
            for child in el:
                child.transform = t @ child.transform
            el.transform = Transform()

        # Ако е обект → директно apply
        if hasattr(el, "apply_transform"):
            el.apply_transform()

        for child in el:
            self._apply_recursive(child)


if __name__ == "__main__":
    CornerMarkers().run()

