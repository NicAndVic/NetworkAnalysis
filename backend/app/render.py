from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import Device, Link, Topology

PT_PER_INCH = 72
DEFAULT_W = 17 * PT_PER_INCH
DEFAULT_H = 11 * PT_PER_INCH

SPEED_COLORS = {"100M": "#f59e0b", "1G": "#2563eb", "10G": "#16a34a", "25G": "#0f766e", "40G": "#9333ea", "100G": "#dc2626"}
MEDIA_DASH = {"fiber": "", "copper": "6,3", "dac": "2,2", "stacking": "1,4"}
DEVICE_FILL = {"switch": "#f8fafc", "firewall": "#fee2e2", "server": "#dcfce7", "ap": "#ede9fe", "isp": "#fef3c7", "router": "#e0f2fe"}


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
        self.edge_segments: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = []

    def _filter_devices(self) -> List[Device]:
        out = []
        for d in self.topo.devices.values():
            if d.device_type == "server" and not self.filters.get("servers", True):
                continue
            if d.device_type == "ap" and not self.filters.get("aps", True):
                continue
            if d.device_type == "cloud":
                p = d.model.lower()
                if p == "aws" and not self.filters.get("aws", True):
                    continue
                if p == "azure" and not self.filters.get("azure", True):
                    continue
                if p not in {"aws", "azure"} and not self.filters.get("other", True):
                    continue
            out.append(d)
        return out

    def _layout(self, devices: List[Device]) -> Tuple[float, float]:
        layers = {"cloud": 0, "internet": 1, "isp": 2, "firewall": 3, "router": 4, "switch": 5, "server": 6, "ap": 6}
        buckets: Dict[int, List[Device]] = {}
        for d in devices:
            buckets.setdefault(layers.get(d.device_type, 5), []).append(d)
        y = 80
        max_w = DEFAULT_W
        for layer in sorted(buckets):
            row = sorted(buckets[layer], key=lambda x: x.hostname)
            x = 80
            for d in row:
                if d.device_type == "ap":
                    d.w, d.h = 140, 64
                elif d.device_type in {"internet", "cloud"}:
                    d.w, d.h = 130, 76
                else:
                    d.w, d.h = 180, 84
                d.x, d.y = x, y
                self.node_boxes[d.id] = Box(x, y, d.w, d.h)
                x += d.w + 52
            max_w = max(max_w, x + 80)
            y += 130
        return max_w, max(DEFAULT_H, y + 240)

    def _clusterize(self, devices: List[Device]) -> None:
        stack_groups: Dict[str, List[Box]] = {}
        ha_groups: Dict[str, List[Box]] = {}
        for d in devices:
            if d.stack_id:
                stack_groups.setdefault(d.stack_id, []).append(self.node_boxes[d.id])
            if d.ha_cluster:
                ha_groups.setdefault(d.ha_cluster, []).append(self.node_boxes[d.id])

        for boxes in list(stack_groups.values()) + list(ha_groups.values()):
            if len(boxes) < 2:
                continue
            x0 = min(b.x for b in boxes) - 16
            y0 = min(b.y for b in boxes) - 16
            x1 = max(b.x + b.w for b in boxes) + 16
            y1 = max(b.y + b.h for b in boxes) + 16
            self.cluster_boxes.append(Box(x0, y0, x1 - x0, y1 - y0))

    def _edge_points(self, src: Box, dst: Box) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        sx, sy = src.x + src.w / 2, src.y + src.h / 2
        dx, dy = dst.x + dst.w / 2, dst.y + dst.h / 2
        if abs(dx - sx) > abs(dy - sy):
            return ((src.x + src.w, sy) if dx > sx else (src.x, sy), (dst.x, dy) if dx > sx else (dst.x + dst.w, dy))
        return ((sx, src.y + src.h) if dy > sy else (sx, src.y), (dx, dst.y) if dy > sy else (dx, dst.y + dst.h))

    def _intersects(self, a: Box, b: Box) -> bool:
        return not (a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y)

    def _label_collides_with_other_edges(self, box: Box, edge_id: str, vertical: bool) -> bool:
        if not vertical:
            return False
        for (p1, p2, eid) in self.edge_segments:
            if eid == edge_id:
                continue
            x0, y0 = min(p1[0], p2[0]), min(p1[1], p2[1])
            x1, y1 = max(p1[0], p2[0]), max(p1[1], p2[1])
            seg_box = Box(x0 - 1, y0 - 1, (x1 - x0) + 2, (y1 - y0) + 2)
            if self._intersects(box, seg_box):
                return True
        return False

    def _place_label(self, p1: Tuple[float, float], p2: Tuple[float, float], text: str, edge_id: str) -> Tuple[float, float]:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        w = max(42.0, len(text) * 6.4)
        h = 12.0
        vertical = abs(p1[0] - p2[0]) < 3
        blockers = list(self.node_boxes.values()) + self.cluster_boxes + self.label_boxes
        offsets = []
        for r in [0, 10, 18, 26, 34, 44, 56, 72, 90, 110]:
            offsets.extend([(0, -8-r), (0, 16+r), (-r, -8), (r, -8), (-r, 16), (r, 16)])
        for ox, oy in offsets:
            x = mx + ox
            y = my + oy
            box = Box(x - w / 2, y - h + 2, w, h)
            if any(self._intersects(box, b) for b in blockers):
                continue
            if self._label_collides_with_other_edges(box, edge_id, vertical):
                continue
            self.label_boxes.append(box)
            return x, y
        # last resort: push to right of the segment to keep off objects
        x, y = mx + 130, my - 14
        box = Box(x - w / 2, y - h + 2, w, h)
        self.label_boxes.append(box)
        return x, y

    def _draw_special_node(self, d: Device) -> str:
        if d.device_type == "internet":
            cx, cy = d.x + d.w / 2, d.y + d.h / 2
            return f'<ellipse class="node internet" id="node-{d.id}" cx="{cx}" cy="{cy}" rx="{d.w/2}" ry="{d.h/2}" fill="#e0f2fe" stroke="#0369a1"/>'
        if d.device_type == "cloud":
            cx, cy = d.x + d.w / 2, d.y + d.h / 2
            if d.model.lower() == "aws":
                pts = [(cx, d.y), (d.x + d.w, cy), (cx, d.y + d.h), (d.x, cy)]
            elif d.model.lower() == "azure":
                pts = [(cx, d.y), (d.x + d.w, d.y + d.h), (d.x, d.y + d.h)]
            else:
                pts = [(d.x + d.w * 0.2, d.y), (d.x + d.w * 0.8, d.y), (d.x + d.w, cy), (d.x + d.w * 0.8, d.y + d.h), (d.x + d.w * 0.2, d.y + d.h), (d.x, cy)]
            pstr = " ".join(f"{x},{y}" for x, y in pts)
            return f'<polygon class="node cloud" id="node-{d.id}" points="{pstr}" fill="#e2e8f0" stroke="#334155"/>'
        fill = DEVICE_FILL.get(d.device_type, "#f8fafc")
        return f'<rect class="node" id="node-{d.id}" x="{d.x}" y="{d.y}" width="{d.w}" height="{d.h}" rx="8" ry="8" fill="{fill}" stroke="#1f2937"/>'

    def render_svg(self) -> str:
        devices = self._filter_devices()
        content_w, content_h = self._layout(devices)
        self._clusterize(devices)

        pages = 1
        legend_top = content_h - 160
        info_boxes = [x for x in [("Routing", self.topo.route_lines), ("DHCP", self.topo.dhcp_lines), ("VLANs", self.topo.vlan_lines)] if x[1]]
        info_needed_h = sum(min(140, 34 + len(lines) * 12) + 10 for _, lines in info_boxes)
        if info_boxes and 20 + info_needed_h > legend_top - 20:
            pages = 2

        canvas_w = content_w if not self.fit_to_page else DEFAULT_W
        canvas_h = (DEFAULT_H * pages) if (self.paginate or self.fit_to_page) else max(content_h, DEFAULT_H * pages)
        vb_w = max(content_w, DEFAULT_W)
        vb_h = max(content_h, DEFAULT_H * pages)

        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {vb_w} {vb_h}">']
        parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')

        for idx, c in enumerate(self.cluster_boxes):
            fill = "#eef2ff" if idx % 2 == 0 else "#fee2e2"
            parts.append(f'<rect class="cluster" x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" fill="{fill}" stroke="#94a3b8" stroke-dasharray="6,2"/>')

        edge_count = 0
        for lk in self.topo.links:
            if lk.src not in self.node_boxes or lk.dst not in self.node_boxes:
                continue
            p1, p2 = self._edge_points(self.node_boxes[lk.src], self.node_boxes[lk.dst])
            edge_id = f"e{edge_count}"
            self.edge_segments.append((p1, p2, edge_id))
            color = SPEED_COLORS.get(lk.speed, "#334155")
            dash = MEDIA_DASH.get(lk.media, "")
            style = f'stroke:{color};stroke-width:2;fill:none'
            if dash:
                style += f';stroke-dasharray:{dash}'
            if lk.stp_blocked:
                style += ';stroke-dasharray:2,2;stroke-width:3'

            if lk.link_type == "trunk":
                nx, ny = p2[1] - p1[1], p1[0] - p2[0]
                norm = math.hypot(nx, ny) or 1.0
                ox, oy = nx / norm * 2.5, ny / norm * 2.5
                parts.append(f'<line class="edge trunk" data-edge-id="{edge_id}" x1="{p1[0]+ox}" y1="{p1[1]+oy}" x2="{p2[0]+ox}" y2="{p2[1]+oy}" style="{style}"/>')
                parts.append(f'<line class="edge trunk" data-edge-id="{edge_id}" x1="{p1[0]-ox}" y1="{p1[1]-oy}" x2="{p2[0]-ox}" y2="{p2[1]-oy}" style="{style}"/>')
            else:
                parts.append(f'<line class="edge" data-edge-id="{edge_id}" x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" style="{style}"/>')

            label = f'{lk.speed}/{lk.media}'
            if lk.link_type == "trunk":
                trunk_name = lk.trunk_id or "LAG"
                label += f' {trunk_name} ({lk.members})'
            if lk.stp_blocked:
                label += ' STP blocked'
            lx, ly = self._place_label(p1, p2, label, edge_id)
            parts.append(f'<text class="edge-label" data-edge-id="{edge_id}" x="{lx}" y="{ly}" text-anchor="middle" font-size="11" fill="#111827">{label}</text>')
            edge_count += 1

        for d in devices:
            parts.append(self._draw_special_node(d))
            parts.append(f'<text x="{d.x+d.w/2}" y="{d.y+17}" text-anchor="middle" font-size="12" font-weight="700">{d.hostname}</text>')
            parts.append(f'<text x="{d.x+d.w/2}" y="{d.y+33}" text-anchor="middle" font-size="10">{d.device_type} {d.model}</text>')
            parts.append(f'<text x="{d.x+d.w/2}" y="{d.y+48}" text-anchor="middle" font-size="10">{" ".join(d.mgmt_ips)}</text>')
            role_text = ", ".join([f"Role: {r}" for r in d.roles])
            if d.stp_root:
                role_text = (role_text + " ").strip() + "STP root"
            parts.append(f'<text x="{d.x+d.w/2}" y="{d.y+63}" text-anchor="middle" font-size="9">{role_text}</text>')

        legend_y = DEFAULT_H - 154
        parts.append(f'<rect class="legend" x="24" y="{legend_y}" width="530" height="126" fill="#fffbeb" stroke="#a16207"/>')
        parts.append(f'<text x="34" y="{legend_y+20}" font-size="13" font-weight="700">Legend</text>')
        parts.append(f'<text x="34" y="{legend_y+40}" font-size="11">Speed colors: 100M amber, 1G blue, 10G green, 25G teal, 40G purple, 100G red</text>')
        parts.append(f'<text x="34" y="{legend_y+58}" font-size="11">Media styles: fiber solid, copper dashed, DAC dotted, stacking sparse dots</text>')
        parts.append(f'<text x="34" y="{legend_y+76}" font-size="11">Trunk = double-line + Trk/Po id and member count</text>')
        parts.append(f'<text x="34" y="{legend_y+94}" font-size="11">STP blocked = dotted emphasized line + label</text>')
        parts.append(f'<text x="34" y="{legend_y+112}" font-size="11">Shading: firewall/server/AP/stack/HA clusters</text>')

        tb_x = vb_w - 360
        tb_y = DEFAULT_H - 118
        parts.append(f'<rect x="{tb_x}" y="{tb_y}" width="336" height="92" fill="#f1f5f9" stroke="#334155"/>')
        parts.append(f'<text x="{tb_x+10}" y="{tb_y+26}" font-size="14" font-weight="700">{self.topo.title}</text>')
        parts.append(f'<text x="{tb_x+10}" y="{tb_y+48}" font-size="11">Paper: 17x11 inches</text>')

        if info_boxes:
            info_x = vb_w - 520
            if pages == 1:
                info_y = 20
            else:
                info_y = DEFAULT_H + 20
            for title, lines in info_boxes:
                height = min(140, 34 + len(lines) * 12)
                parts.append(f'<rect class="info-box" x="{info_x}" y="{info_y}" width="490" height="{height}" fill="#f8fafc" stroke="#64748b"/>')
                parts.append(f'<text x="{info_x+8}" y="{info_y+18}" font-size="12" font-weight="700">{title}</text>')
                y = info_y + 34
                for line in lines[:8]:
                    parts.append(f'<text x="{info_x+8}" y="{y}" font-size="10">{line}</text>')
                    y += 12
                info_y += height + 10

        parts.append("</svg>")
        return "\n".join(parts)
