from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import Device, Topology

PT_PER_INCH = 72
DEFAULT_W = 17 * PT_PER_INCH
DEFAULT_H = 11 * PT_PER_INCH

SPEED_COLORS = {
    "100M": "#f59e0b",
    "1G": "#2563eb",
    "10G": "#16a34a",
    "25G": "#0f766e",
    "40G": "#9333ea",
    "100G": "#dc2626",
}
MEDIA_DASH = {"fiber": "", "copper": "6,3", "dac": "2,2", "stacking": "1,5"}
DEVICE_FILL = {
    "switch": "#f8fafc",
    "firewall": "#fee2e2",
    "server": "#dcfce7",
    "ap": "#ede9fe",
    "isp": "#fef3c7",
    "router": "#e0f2fe",
    "cloud": "#dbeafe",
    "internet": "#e5e7eb",
}


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
        self.cluster_boxes: List[Tuple[str, Box]] = []
        self.label_boxes: List[Box] = []
        self.edge_segments: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = []

    def _filter_devices(self) -> List[Device]:
        out: List[Device] = []
        for device in self.topo.devices.values():
            if device.device_type == "server" and not self.filters.get("servers", True):
                continue
            if device.device_type == "ap" and not self.filters.get("aps", True):
                continue
            if device.device_type == "cloud":
                provider = device.model.lower()
                if provider == "aws" and not self.filters.get("aws", True):
                    continue
                if provider == "azure" and not self.filters.get("azure", True):
                    continue
                if provider not in {"aws", "azure"} and not self.filters.get("other", True):
                    continue
            out.append(device)
        return out

    def _layout(self, devices: List[Device]) -> Tuple[float, float]:
        layers = {
            "cloud": 0,
            "internet": 1,
            "isp": 2,
            "firewall": 3,
            "router": 4,
            "switch": 5,
            "server": 6,
            "ap": 6,
        }
        by_layer: Dict[int, List[Device]] = {}
        for device in devices:
            by_layer.setdefault(layers.get(device.device_type, 5), []).append(device)

        y = 70.0
        max_x = DEFAULT_W
        for layer in sorted(by_layer):
            row = sorted(by_layer[layer], key=lambda item: item.hostname)
            x = 60.0
            for device in row:
                if device.device_type == "ap":
                    device.w, device.h = 130, 60
                elif device.device_type in {"internet", "cloud", "isp"}:
                    device.w, device.h = 148, 70
                else:
                    device.w, device.h = 182, 86
                device.x, device.y = x, y
                self.node_boxes[device.id] = Box(device.x, device.y, device.w, device.h)
                x += device.w + 48
            max_x = max(max_x, x + 50)
            y += 125

        return max_x, max(DEFAULT_H, y + 170)

    def _clusterize(self, devices: List[Device]) -> None:
        stack_groups: Dict[str, List[Box]] = {}
        ha_groups: Dict[str, List[Box]] = {}
        for device in devices:
            if device.id not in self.node_boxes:
                continue
            if device.stack_id:
                stack_groups.setdefault(device.stack_id, []).append(self.node_boxes[device.id])
            if device.ha_cluster:
                ha_groups.setdefault(device.ha_cluster, []).append(self.node_boxes[device.id])

        for group_id, boxes in stack_groups.items():
            if len(boxes) < 2:
                continue
            self.cluster_boxes.append((f"stack:{group_id}", self._boxes_envelope(boxes)))
        for group_id, boxes in ha_groups.items():
            if len(boxes) < 2:
                continue
            self.cluster_boxes.append((f"ha:{group_id}", self._boxes_envelope(boxes)))

    @staticmethod
    def _boxes_envelope(boxes: List[Box]) -> Box:
        x0 = min(box.x for box in boxes) - 18
        y0 = min(box.y for box in boxes) - 18
        x1 = max(box.x + box.w for box in boxes) + 18
        y1 = max(box.y + box.h for box in boxes) + 18
        return Box(x0, y0, x1 - x0, y1 - y0)

    def _edge_points(self, src: Box, dst: Box) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        sx, sy = src.x + src.w / 2, src.y + src.h / 2
        dx, dy = dst.x + dst.w / 2, dst.y + dst.h / 2
        if abs(dx - sx) > abs(dy - sy):
            left = (src.x + src.w, sy) if dx > sx else (src.x, sy)
            right = (dst.x, dy) if dx > sx else (dst.x + dst.w, dy)
            return left, right
        top = (sx, src.y + src.h) if dy > sy else (sx, src.y)
        bottom = (dx, dst.y) if dy > sy else (dx, dst.y + dst.h)
        return top, bottom

    @staticmethod
    def _intersects(a: Box, b: Box) -> bool:
        return not (a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y)

    def _place_label(self, p1: Tuple[float, float], p2: Tuple[float, float], text: str, edge_id: str) -> Tuple[float, float]:
        mid_x = (p1[0] + p2[0]) / 2
        mid_y = (p1[1] + p2[1]) / 2
        width = max(40.0, len(text) * 6.2)
        height = 12.0
        vertical = abs(p1[0] - p2[0]) < 2.5

        blockers = list(self.node_boxes.values()) + [box for _, box in self.cluster_boxes] + self.label_boxes
        offsets = [(0, -8), (0, 12), (-14, -8), (14, -8), (0, -22), (0, 24), (20, 20), (-20, 20)]

        for ox, oy in offsets:
            x = mid_x + ox
            y = mid_y + oy
            candidate = Box(x - width / 2, y - height + 2, width, height)
            if any(self._intersects(candidate, blocker) for blocker in blockers):
                continue
            if vertical and self._overlaps_other_edge(candidate, edge_id):
                continue
            self.label_boxes.append(candidate)
            return x, y

        fallback = Box(mid_x + 40 - width / 2, mid_y - height + 2, width, height)
        self.label_boxes.append(fallback)
        return mid_x + 40, mid_y

    def _overlaps_other_edge(self, box: Box, edge_id: str) -> bool:
        for p1, p2, eid in self.edge_segments:
            if eid == edge_id:
                continue
            x0, y0 = min(p1[0], p2[0]), min(p1[1], p2[1])
            x1, y1 = max(p1[0], p2[0]), max(p1[1], p2[1])
            expanded = Box(x0 - 1, y0 - 1, (x1 - x0) + 2, (y1 - y0) + 2)
            if self._intersects(box, expanded):
                return True
        return False

    def _draw_node(self, device: Device) -> str:
        fill = DEVICE_FILL.get(device.device_type, "#ffffff")
        return (
            f'<rect class="node {device.device_type}" x="{device.x}" y="{device.y}" '
            f'width="{device.w}" height="{device.h}" rx="8" fill="{fill}" stroke="#1f2937"/>'
        )

    def render_svg(self) -> str:
        devices = self._filter_devices()
        content_w, content_h = self._layout(devices)
        self._clusterize(devices)

        info_boxes = [
            ("Routing table", self.topo.route_lines),
            ("DHCP scopes", self.topo.dhcp_lines),
            ("VLANs", self.topo.vlan_lines),
        ]
        info_boxes = [(title, lines) for title, lines in info_boxes if lines]

        legend_h = 126
        legend_y = DEFAULT_H - 154
        info_needed_h = sum(min(145, 34 + len(lines) * 12) + 10 for _, lines in info_boxes)
        needs_second_page = bool(info_boxes and (20 + info_needed_h > legend_y - 20))
        pages = 2 if needs_second_page else 1

        view_w = max(content_w, DEFAULT_W)
        view_h = max(content_h, DEFAULT_H * pages)

        if self.fit_to_page:
            canvas_w = DEFAULT_W
            canvas_h = DEFAULT_H * pages
        elif self.paginate:
            canvas_w = DEFAULT_W
            canvas_h = DEFAULT_H * pages
        else:
            canvas_w = view_w
            canvas_h = view_h

        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {view_w} {view_h}">',
            '<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>',
        ]

        for cluster_id, box in self.cluster_boxes:
            cluster_type = "stack" if cluster_id.startswith("stack:") else "ha"
            fill = "#e0e7ff" if cluster_type == "stack" else "#ffe4e6"
            parts.append(
                f'<rect class="cluster {cluster_type}" x="{box.x}" y="{box.y}" width="{box.w}" height="{box.h}" '
                f'fill="{fill}" stroke="#64748b" stroke-dasharray="5,3"/>'
            )

        edge_count = 0
        for link in self.topo.links:
            if link.src not in self.node_boxes or link.dst not in self.node_boxes:
                continue
            p1, p2 = self._edge_points(self.node_boxes[link.src], self.node_boxes[link.dst])
            edge_id = f"e{edge_count}"
            self.edge_segments.append((p1, p2, edge_id))
            edge_count += 1

            color = SPEED_COLORS.get(link.speed, "#334155")
            dash = MEDIA_DASH.get(link.media, "")
            stroke_width = 2.2
            style = f"stroke:{color};stroke-width:{stroke_width};fill:none"
            if dash:
                style += f";stroke-dasharray:{dash}"
            if link.stp_blocked:
                style += ";stroke-dasharray:2,2;stroke-width:3"

            if link.link_type == "trunk" and link.members >= 2:
                nx, ny = p2[1] - p1[1], p1[0] - p2[0]
                norm = math.hypot(nx, ny) or 1.0
                ox, oy = nx / norm * 2.4, ny / norm * 2.4
                parts.append(
                    f'<line class="edge trunk" data-edge-id="{edge_id}" x1="{p1[0]+ox}" y1="{p1[1]+oy}" '
                    f'x2="{p2[0]+ox}" y2="{p2[1]+oy}" style="{style}"/>'
                )
                parts.append(
                    f'<line class="edge trunk" data-edge-id="{edge_id}" x1="{p1[0]-ox}" y1="{p1[1]-oy}" '
                    f'x2="{p2[0]-ox}" y2="{p2[1]-oy}" style="{style}"/>'
                )
            else:
                parts.append(
                    f'<line class="edge" data-edge-id="{edge_id}" x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" style="{style}"/>'
                )

            label = f"{link.speed}/{link.media}"
            if link.link_type == "trunk" and link.members >= 2:
                label += f" {link.trunk_id or 'LAG'} members={link.members}"
            if link.stp_blocked:
                label += " STP blocked"
            lx, ly = self._place_label(p1, p2, label, edge_id)
            parts.append(
                f'<text class="edge-label" data-edge-id="{edge_id}" x="{lx}" y="{ly}" text-anchor="middle" font-size="11" fill="#111827">{label}</text>'
            )

        for device in devices:
            parts.append(self._draw_node(device))
            parts.append(f'<text x="{device.x + device.w/2}" y="{device.y + 18}" text-anchor="middle" font-size="12" font-weight="700">{device.hostname}</text>')
            parts.append(f'<text x="{device.x + device.w/2}" y="{device.y + 34}" text-anchor="middle" font-size="10">{device.device_type} {device.model}</text>')
            parts.append(f'<text x="{device.x + device.w/2}" y="{device.y + 50}" text-anchor="middle" font-size="9">{" ".join(device.mgmt_ips)}</text>')
            role_text = ", ".join(device.roles)
            if device.stp_root:
                role_text = (role_text + " " if role_text else "") + "STP root"
            parts.append(f'<text x="{device.x + device.w/2}" y="{device.y + 66}" text-anchor="middle" font-size="9">{role_text}</text>')

        parts.append(f'<rect class="legend" x="24" y="{legend_y}" width="560" height="{legend_h}" fill="#fffbeb" stroke="#a16207"/>')
        parts.append(f'<text x="34" y="{legend_y + 20}" font-size="13" font-weight="700">Legend</text>')
        parts.append(f'<text x="34" y="{legend_y + 40}" font-size="11">Speed→color: 100M amber, 1G blue, 10G green, 25G teal, 40G purple, 100G red</text>')
        parts.append(f'<text x="34" y="{legend_y + 58}" font-size="11">Media→style: fiber solid, copper dashed, DAC dotted, stacking sparse dots</text>')
        parts.append(f'<text x="34" y="{legend_y + 76}" font-size="11">Trunk representation: double-line, label includes trunk id + member count</text>')
        parts.append(f'<text x="34" y="{legend_y + 94}" font-size="11">STP blocked shown only when data exists</text>')
        parts.append(f'<text x="34" y="{legend_y + 112}" font-size="11">Shading by type: switch/firewall/server/AP plus stack and HA clusters</text>')

        title_x = view_w - 360
        title_y = DEFAULT_H - 118
        parts.append(f'<rect class="title-block" x="{title_x}" y="{title_y}" width="336" height="92" fill="#f1f5f9" stroke="#334155"/>')
        parts.append(f'<text x="{title_x + 10}" y="{title_y + 28}" font-size="14" font-weight="700">{self.topo.title}</text>')
        parts.append(f'<text x="{title_x + 10}" y="{title_y + 50}" font-size="11">Paper: 17x11 inches</text>')

        if info_boxes:
            info_x = view_w - 520
            info_y = 20 if not needs_second_page else DEFAULT_H + 20
            for title, lines in info_boxes:
                box_h = min(145, 34 + len(lines) * 12)
                parts.append(f'<rect class="info-box" x="{info_x}" y="{info_y}" width="490" height="{box_h}" fill="#f8fafc" stroke="#64748b"/>')
                parts.append(f'<text x="{info_x + 8}" y="{info_y + 18}" font-size="12" font-weight="700">{title}</text>')
                line_y = info_y + 34
                for line in lines[:8]:
                    parts.append(f'<text x="{info_x + 8}" y="{line_y}" font-size="10">{line}</text>')
                    line_y += 12
                info_y += box_h + 10

        parts.append("</svg>")
        return "\n".join(parts)
