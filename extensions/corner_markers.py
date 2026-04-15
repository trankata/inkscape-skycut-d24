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
        pars.add_argument("--triangle_size_mm", type=float, default=4.0,
                         help="Размер на триъгълничето-индикатор")

    def effect(self):
        svg = self.svg

        # =========================================================
        # НАМИРАМЕ CUT СЛОЯ АВТОМАТИЧНО
        # =========================================================
        cut_layer = None
        for layer in svg.xpath("//svg:g[@inkscape:groupmode='layer']"):
            if layer.label == "Cut":
                cut_layer = layer
                break

        if cut_layer is None:
            inkex.errormsg("Не е намерен слой с име 'Cut'!")
            return

        # Взимаме bounding box на целия Cut слой (включва групи)
        bbox = cut_layer.bounding_box()
        if bbox is None:
            inkex.errormsg("Слоят 'Cut' е празен!")
            return

        # ---------- ПАРАМЕТРИ ----------
        offset        = svg.unittouu(f"{self.options.offset_mm}mm")
        arm           = svg.unittouu("15mm")
        stroke        = svg.unittouu("1mm")
        triangle_size = svg.unittouu(f"{self.options.triangle_size_mm}mm")

        # ---------- ИЗЧИСЛЯВАНЕ НА ОБХВАТ ----------
        minx = bbox.left   - offset
        maxx = bbox.right  + offset
        miny = bbox.top    - offset   # ГОРЕ (по-малка стойност)
        maxy = bbox.bottom + offset   # ДОЛУ (по-голяма стойност)

        # ---------- СЛОЙ MARK ----------
        mark_layer = None
        for layer in svg.xpath("//svg:g[@inkscape:groupmode='layer']"):
            if layer.label == "Mark":
                mark_layer = layer
                break

        if mark_layer is None:
            mark_layer = Layer.new("Mark")
            svg.add(mark_layer)

        # 🔒 ЗАКЛЮЧВАНЕ НА MARK LAYER
        mark_layer.set("sodipodi:insensitive", "true")

        style = Style({
            "stroke":          "#000000",
            "stroke-width":    stroke,
            "fill":            "none",
            "stroke-linecap":  "square"
        })

        # ---------- СЪЗДАВАНЕ НА 4 L-ОБРАЗНИ МАРКЕРИ ----------
        corners = [
            [(minx,       miny + arm), (minx, miny), (minx + arm, miny)],   # ГОРЕ-ЛЯВО
            [(maxx - arm, miny),       (maxx, miny), (maxx,       miny + arm)],  # ГОРЕ-ДЯСНО
            [(maxx,       maxy - arm), (maxx, maxy), (maxx - arm, maxy)],   # ДОЛУ-ДЯСНО
            [(minx + arm, maxy),       (minx, maxy), (minx,       maxy - arm)],  # ДОЛУ-ЛЯВО
        ]

        for i, pts in enumerate(corners):
            path = PathElement()
            path.path = inkex.Path(
                f"M {pts[0][0]},{pts[0][1]} "
                f"L {pts[1][0]},{pts[1][1]} "
                f"L {pts[2][0]},{pts[2][1]}"
            )
            path.style = style
            path.set('data-type', 'corner')
            path.set('data-index', str(i))
            mark_layer.add(path)

        # =========================================================
        # ТРИЪГЪЛНИЧЕ МЕЖДУ ДОЛНИТЕ МАРКЕРИ - БЕЗ STROKE
        # =========================================================
        center_x     = (minx + maxx) / 2
        tip_y        = maxy
        left_tip_x   = center_x - (triangle_size / 2)
        right_tip_x  = center_x + (triangle_size / 2)
        base_y       = maxy + triangle_size

        triangle = PathElement()
        triangle.path = inkex.Path(
            f"M {center_x},{tip_y} "
            f"L {left_tip_x},{base_y} "
            f"L {right_tip_x},{base_y} "
            f"L {center_x},{tip_y}"
        )
        triangle_style = Style({
            "stroke":          "none",
            "stroke-width":    0,
            "fill":            "#000000",
            "stroke-linejoin": "miter"
        })
        triangle.style = triangle_style
        triangle.set('data-type', 'triangle')
        mark_layer.add(triangle)

        # =========================================================
        # АВТОМАТИЧНО СКРИВАНЕ НА СЛОЙ "CUT"
        # =========================================================
        cut_layer.style['display'] = 'none'
        inkex.errormsg("✅ Маркерите са създадени. Слоят 'Cut' беше скрит за печат. 🖨️")


if __name__ == "__main__":
    CornerMarkers().run()
