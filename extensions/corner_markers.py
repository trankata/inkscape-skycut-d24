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
        selection = svg.selection

        if not selection:
            inkex.errormsg("Няма избрани обекти!")
            return

        # =========================================================
        # ПРИЛАГАНЕ НА ТРАНСФОРМАЦИИ
        # =========================================================
        for el in selection.values():
            self._apply_recursive(el)

        # ---------- ПАРАМЕТРИ ----------
        offset = svg.unittouu(f"{self.options.offset_mm}mm")
        arm = svg.unittouu("15mm")
        stroke = svg.unittouu("1mm")
        triangle_size = svg.unittouu(f"{self.options.triangle_size_mm}mm")

        # ---------- ИЗЧИСЛЯВАНЕ НА ОБХВАТ ----------
        bboxes = [el.bounding_box() for el in selection.values()]
        minx = min(b.left for b in bboxes) - offset
        maxx = max(b.right for b in bboxes) + offset
        miny = min(b.top for b in bboxes) - offset   # ГОРЕ (по-малка стойност)
        maxy = max(b.bottom for b in bboxes) + offset # ДОЛУ (по-голяма стойност)

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
            "stroke": "#000000",
            "stroke-width": stroke,
            "fill": "none",
            "stroke-linecap": "square"
        })

        # ---------- СЪЗДАВАНЕ НА 4 L-ОБРАЗНИ МАРКЕРИ ----------
        corners = [
            [(minx, miny + arm), (minx, miny), (minx + arm, miny)],    # ГОРЕ-ЛЯВО
            [(maxx - arm, miny), (maxx, miny), (maxx, miny + arm)],    # ГОРЕ-ДЯСНО
            [(maxx, maxy - arm), (maxx, maxy), (maxx - arm, maxy)],    # ДОЛУ-ДЯСНО
            [(minx + arm, maxy), (minx, maxy), (minx, maxy - arm)],    # ДОЛУ-ЛЯВО
        ]

        for i, pts in enumerate(corners):
            path = PathElement()
            path.path = inkex.Path([
                ('M', pts[0]),
                ('L', pts[1]),
                ('L', pts[2])
            ])
            path.style = style
            path.set('data-type', 'corner')  # Маркираме като ъглов маркер
            path.set('data-index', str(i))   # Номер на маркера
            mark_layer.add(path)

        # =========================================================
        # ТРИЪГЪЛНИЧЕ МЕЖДУ ДОЛНИТЕ МАРКЕРИ - БЕЗ STROKE
        # =========================================================
        
        # Изчисляваме центъра между долните два маркера
        center_x = (minx + maxx) / 2
        
        # Триъгълник със върха НАДОЛУ (▼) и върха на нивото на маркерите
        # Върхът (A) - на нивото на долните маркери (maxy)
        # Основата (B и C) - под маркерите
        
        # Върхът на триъгълника (A) - на нивото на долните маркери
        tip_y = maxy  # ТОЧНО на нивото на долните маркери
        
        # Долни върхове на триъгълника (B и C) - под маркерите
        left_tip_x = center_x - (triangle_size / 2)
        right_tip_x = center_x + (triangle_size / 2)
        base_y = maxy + triangle_size  # ПОД долните маркери
        
        triangle_pts = [
            (center_x, tip_y),      # A - ВРЪХ на нивото на маркерите
            (left_tip_x, base_y),   # B - долен ляв (под маркерите)
            (right_tip_x, base_y),  # C - долен десен (под маркерите)
            (center_x, tip_y)       # Затваряне
        ]
        
        # Създаваме триъгълника БЕЗ STROKE
        triangle = PathElement()
        triangle.path = inkex.Path([
            ('M', triangle_pts[0]),
            ('L', triangle_pts[1]),
            ('L', triangle_pts[2]),
            ('L', triangle_pts[0])  # Затваряне
        ])
        
        triangle_style = Style({
            "stroke": "none",      # БЕЗ stroke (контур)
            "stroke-width": 0,     # Дебелина 0
            "fill": "#000000",     # Само запълнен черен
            "stroke-linejoin": "miter"
        })
        triangle.style = triangle_style
        triangle.set('data-type', 'triangle')  # МАРКИРАМЕ КАТО ТРИЪГЪЛНИК!
        
        mark_layer.add(triangle)

        # =========================================================
        # АВТОМАТИЧНО СКРИВАНЕ НА СЛОЙ "CUT"
        # =========================================================
        cut_layer_found = False
        for layer in svg.xpath("//svg:g[@inkscape:groupmode='layer']"):
            if layer.label == "Cut":
                layer.style['display'] = 'none'
                cut_layer_found = True
                break
        
        if cut_layer_found:
            inkex.errormsg("Слоят 'Cut' беше скрит автоматично за по-сигурен печат. 🖨️")
        else:
            inkex.errormsg("Внимание: Слой с име 'Cut' не беше открит. ⚠️")

    def _apply_recursive(self, el):
        if el.transform:
            el.apply_transform()
        
        if isinstance(el, Group):
            for child in el:
                self._apply_recursive(child)

if __name__ == "__main__":
    CornerMarkers().run()
