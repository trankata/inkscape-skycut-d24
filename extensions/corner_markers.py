#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Corner Markers (L-shaped) – Inkscape extension
# Copyright (C) 2025 Anton Kutrubiev
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


import inkex
from inkex import PathElement, Layer, Style

class CornerMarkers(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--offset_mm", type=float, default=5.0)

    def effect(self):
        svg = self.svg
        selection = svg.selection

        if not selection:
            inkex.errormsg("No objects selected")
            return

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

if __name__ == "__main__":
    CornerMarkers().run()
