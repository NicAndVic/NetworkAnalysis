from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import Device, Link, Topology

PT_PER_INCH = 72
DEFAULT_W = 17 * PT_PER_INCH
DEFAULT_H = 11 * PT_PER_INCH

SPEED_COLORS = {"100M": "#f59e0b", "1G": "#2563eb", "10G": "#16a34a", "40G": "#9333ea", "100G": "#dc2626"}
MEDIA_DASH = {"fiber": "", "copper": "6,3", "dac": "2,2", "stacking": "1,4"}


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float


class Renderer:
    def __init__(self, topo: Topology, filters: Dict[str, bool], paginate: bool, fit_to_page: bool):
        self.topo = topo
        self.filters = filters
        self.paginate = paginate
        self.fit_to_page = fit_to_page
        self.node_boxes: Dict[str, Box] = {}
        self.cluster_boxes: List[Box] = []
        self.label_boxes: List[Box] = []

    def _filter_devices(self) -> List[Device]:
        out = []
        for d in self.topo.devices.values():
            if d.device_type == "server" and not self.filters.get("servers", True):
                continue
            if d.device_type == "ap" and not self.filters.get("aps", True):
                continue
            out.append(d)
        return out

    def _layout(self, devices: List[Device]) -> Tuple[float, float]:
        layers = {"cloud": 0, "firewall": 1, "router": 2, "switch": 3, "server": 4, "ap": 4}
        buckets: Dict[int, List[Device]] = {}
        for d in devices:
            buckets.setdefault(layers.get(d.device_type, 3), []).append(d)
        y = 110
        max_w = DEFAULT_W
        for layer in sorted(buckets):
            row = buckets[layer]
            x = 110
            for d in row:
                d.x, d.y = x, y
                self.node_boxes[d.id] = Box(x, y, d.w, d.h)
                x += d.w + 80
            max_w = max(max_w, x + 100)
            y += 150
        h = max(DEFAULT_H, y + 220)
        return max_w, h

    def _clusterize(self) -> None:
        stack_groups: Dict[str, List[Box]] = {}
        ha_groups: Dict[str, List[Box]] = {}
        for d in self.topo.devices.values():
            if d.id not in self.node_boxes:
                continue
            if d.stack_id:
                stack_groups.setdefault(d.stack_id, []).append(self.node_boxes[d.id])
            if d.ha_cluster:
                ha_groups.setdefault(d.ha_cluster, []).append(self.node_boxes[d.id])
        for boxes in list(stack_groups.values()) + list(ha_groups.values()):
            x0 = min(b.x for b in boxes) - 20
            y0 = min(b.y for b in boxes) - 20
            x1 = max(b.x + b.w for b in boxes) + 20
            y1 = max(b.y + b.h for b in boxes) + 20
            self.cluster_boxes.append(Box(x0, y0, x1 - x0, y1 - y0))

    def _edge_points(self, src: Box, dst: Box) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        sx, sy = src.x + src.w / 2, src.y + src.h / 2
        dx, dy = dst.x + dst.w / 2, dst.y + dst.h / 2
        if abs(dx - sx) > abs(dy - sy):
            s = (src.x + src.w, sy) if dx > sx else (src.x, sy)
            d = (dst.x, dy) if dx > sx else (dst.x + dst.w, dy)
        else:
            s = (sx, src.y + src.h) if dy > sy else (sx, src.y)
            d = (dx, dst.y) if dy > sy else (dx, dst.y + dst.h)
        return s, d

    def _intersects(self, b: Box, others: List[Box]) -> bool:
        for o in others:
            if not (b.x + b.w < o.x or o.x + o.w < b.x or b.y + b.h < o.y or o.y + o.h < b.y):
                return True
        return False

    def _place_label(self, p1: Tuple[float, float], p2: Tuple[float, float], text: str) -> Tuple[float, float]:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        w = max(45, len(text) * 6)
        h = 12
        blockers = list(self.node_boxes.values()) + self.cluster_boxes + self.label_boxes
        for radius in [0, 10, 18, 26, 34, 44, 56, 70]:
            for ox, oy in [(0, -14), (0, 8), (0, -2), (-radius, -14), (radius, -14), (-radius, 8), (radius, 8), (0, -14-radius), (0, 8+radius)]:
                x = mx - w / 2 + ox
                y = my + oy
                box = Box(x, y, w, h)
                if not self._intersects(box, blockers):
                    self.label_boxes.append(box)
                    return x, y + h
        # As a safe fallback push away from center to reduce overlap risk.
        x, y = mx - w / 2 + 80, my - h - 28
        box = Box(x, y, w, h)
        self.label_boxes.append(box)
        return x, y + h

    def render_svg(self) -> str:
        devices = self._filter_devices()
        w, h = self._layout(devices)
        self._clusterize()

        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">']
        parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')

        for idx, c in enumerate(self.cluster_boxes):
            fill = "#eef2ff" if idx % 2 == 0 else "#ecfeff"
            parts.append(f'<rect class="cluster" x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" fill="{fill}" stroke="#94a3b8" stroke-dasharray="6,2"/>')

        for lk in self.topo.links:
            if lk.src not in self.node_boxes or lk.dst not in self.node_boxes:
                continue
            p1, p2 = self._edge_points(self.node_boxes[lk.src], self.node_boxes[lk.dst])
            color = SPEED_COLORS.get(lk.speed, "#334155")
            dash = MEDIA_DASH.get(lk.media, "")
            style = f'stroke:{color};stroke-width:2;fill:none'
            if dash:
                style += f';stroke-dasharray:{dash}'
            if lk.stp_blocked:
                style += ';stroke-dasharray:2,2;stroke-width:3'
            if lk.link_type == "trunk":
                nx, ny = p2[1] - p1[1], p1[0] - p2[0]
                norm = math.hypot(nx, ny) or 1
                ox, oy = nx / norm * 2.5, ny / norm * 2.5
                parts.append(f'<line class="edge trunk" x1="{p1[0]+ox}" y1="{p1[1]+oy}" x2="{p2[0]+ox}" y2="{p2[1]+oy}" style="{style}"/>')
                parts.append(f'<line class="edge trunk" x1="{p1[0]-ox}" y1="{p1[1]-oy}" x2="{p2[0]-ox}" y2="{p2[1]-oy}" style="{style}"/>')
            else:
                parts.append(f'<line class="edge" x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" style="{style}"/>')
            label = f'{lk.speed}/{lk.media}' + (f' {lk.members}x' if lk.link_type == "trunk" else "") + (" STP-BLK" if lk.stp_blocked else "")
            lx, ly = self._place_label(p1, p2, label)
            parts.append(f'<text class="edge-label" x="{lx}" y="{ly}" font-size="11" fill="#111827">{label}</text>')

        for d in devices:
            parts.append(f'<rect class="node" id="node-{d.id}" x="{d.x}" y="{d.y}" width="{d.w}" height="{d.h}" rx="8" ry="8" fill="#f8fafc" stroke="#1f2937"/>')
            roles = ", ".join(d.roles)
            stp = " STP-Root" if d.stp_root else ""
            parts.append(f'<text x="{d.x+8}" y="{d.y+18}" font-size="12" font-weight="700">{d.hostname}</text>')
            parts.append(f'<text x="{d.x+8}" y="{d.y+34}" font-size="11">{d.device_type} {d.model}</text>')
            parts.append(f'<text x="{d.x+8}" y="{d.y+50}" font-size="10">{", ".join(d.mgmt_ips)}</text>')
            parts.append(f'<text x="{d.x+8}" y="{d.y+66}" font-size="10">{roles}{stp}</text>')

        legend_y = h - 150
        parts.append(f'<rect x="24" y="{legend_y}" width="420" height="120" fill="#fffbeb" stroke="#a16207"/>')
        parts.append(f'<text x="34" y="{legend_y+20}" font-size="13" font-weight="700">Legend</text>')
        parts.append(f'<text x="34" y="{legend_y+40}" font-size="11">Speed colors: 100M amber, 1G blue, 10G green, 40G purple, 100G red</text>')
        parts.append(f'<text x="34" y="{legend_y+57}" font-size="11">Media lines: fiber solid, copper dashed, DAC dotted, stacking sparse dots</text>')
        parts.append(f'<text x="34" y="{legend_y+74}" font-size="11">Trunk: double-line with member count; STP blocked: dotted + STP-BLK label</text>')
        parts.append(f'<text x="34" y="{legend_y+91}" font-size="11">Shading: stack / HA cluster boundaries</text>')

        parts.append(f'<rect x="{w-370}" y="{h-120}" width="346" height="96" fill="#f1f5f9" stroke="#334155"/>')
        parts.append(f'<text x="{w-360}" y="{h-92}" font-size="14" font-weight="700">{self.topo.title}</text>')
        parts.append(f'<text x="{w-360}" y="{h-72}" font-size="11">Paper: 17x11 in</text>')

        info_x = w - 520
        info_y = 20
        for title, lines in [("Routing", self.topo.route_lines), ("DHCP", self.topo.dhcp_lines), ("VLANs", self.topo.vlan_lines)]:
            if not lines:
                continue
            height = min(120, 30 + len(lines) * 14)
            parts.append(f'<rect class="info-box" x="{info_x}" y="{info_y}" width="490" height="{height}" fill="#f8fafc" stroke="#64748b"/>')
            parts.append(f'<text x="{info_x+8}" y="{info_y+18}" font-size="12" font-weight="700">{title}</text>')
            y = info_y + 34
            for line in lines[:6]:
                parts.append(f'<text x="{info_x+8}" y="{y}" font-size="10">{line}</text>')
                y += 12
            info_y += height + 12

        parts.append("</svg>")
        return "\n".join(parts)
