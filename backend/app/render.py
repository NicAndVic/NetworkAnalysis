from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import Device, Link, Topology

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


@dataclass
class RoutedEdge:
    edge_id: str
    link: Link
    points: List[Tuple[float, float]]


class Renderer:
    def __init__(self, topo: Topology, filters: Dict[str, bool], paginate: bool, fit_to_page: bool):
        self.topo = topo
        self.filters = filters
        self.paginate = paginate
        self.fit_to_page = fit_to_page

        self.node_boxes: Dict[str, Box] = {}
        self.cluster_boxes: List[Tuple[str, Box]] = []
        self.row_channels: List[float] = []
        self.col_channels: List[float] = []
        self.channel_use_h: Dict[float, int] = {}
        self.channel_use_v: Dict[float, int] = {}
        self.label_boxes: List[Box] = []

    def _filter_devices(self) -> List[Device]:
        devices: List[Device] = []
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
            devices.append(device)
        return devices

    def _layout(self, devices: List[Device]) -> Tuple[float, float, Dict[int, List[Device]]]:
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
        prev_row_bottom: float | None = None
        self.row_channels = []

        for layer in sorted(by_layer):
            row = sorted(by_layer[layer], key=lambda item: item.hostname)
            x = 60.0
            row_top = y
            row_bottom = y
            for device in row:
                if device.device_type == "ap":
                    device.w, device.h = 130, 60
                elif device.device_type in {"internet", "cloud", "isp"}:
                    device.w, device.h = 148, 70
                else:
                    device.w, device.h = 182, 86
                device.x, device.y = x, y
                self.node_boxes[device.id] = Box(device.x, device.y, device.w, device.h)
                row_bottom = max(row_bottom, y + device.h)
                x += device.w + 48
            max_x = max(max_x, x + 50)
            if prev_row_bottom is not None:
                self.row_channels.append((prev_row_bottom + row_top) / 2)
            prev_row_bottom = row_bottom
            y = row_bottom + 39

        all_x = sorted({round(box.x - 24, 1) for box in self.node_boxes.values()} | {round(box.x + box.w + 24, 1) for box in self.node_boxes.values()})
        self.col_channels = all_x
        if self.node_boxes:
            top = min(box.y for box in self.node_boxes.values()) - 26
            bottom = max(box.y + box.h for box in self.node_boxes.values()) + 26
            self.row_channels = sorted(set(self.row_channels + [top, bottom]))
        return max_x, max(DEFAULT_H, y + 170), by_layer

    def _clusterize(self, devices: List[Device]) -> None:
        self.cluster_boxes = []
        stack_groups: Dict[str, List[Box]] = {}
        ha_groups: Dict[str, List[Box]] = {}
        for device in devices:
            box = self.node_boxes.get(device.id)
            if not box:
                continue
            if device.stack_id:
                stack_groups.setdefault(device.stack_id, []).append(box)
            if device.ha_cluster:
                ha_groups.setdefault(device.ha_cluster, []).append(box)

        for group_id, boxes in stack_groups.items():
            if len(boxes) >= 2:
                self.cluster_boxes.append((f"stack:{group_id}", self._boxes_envelope(boxes)))
        for group_id, boxes in ha_groups.items():
            if len(boxes) >= 2:
                self.cluster_boxes.append((f"ha:{group_id}", self._boxes_envelope(boxes)))

    @staticmethod
    def _boxes_envelope(boxes: List[Box]) -> Box:
        x0 = min(box.x for box in boxes) - 18
        y0 = min(box.y for box in boxes) - 18
        x1 = max(box.x + box.w for box in boxes) + 18
        y1 = max(box.y + box.h for box in boxes) + 18
        return Box(x0, y0, x1 - x0, y1 - y0)

    def _ports(self, box: Box) -> Dict[str, Tuple[float, float]]:
        return {
            "N": (box.x + box.w / 2, box.y),
            "E": (box.x + box.w, box.y + box.h / 2),
            "S": (box.x + box.w / 2, box.y + box.h),
            "W": (box.x, box.y + box.h / 2),
        }

    @staticmethod
    def _point_in_box(x: float, y: float, box: Box) -> bool:
        return box.x < x < box.x + box.w and box.y < y < box.y + box.h

    @staticmethod
    def _seg_intersects_box(a: Tuple[float, float], b: Tuple[float, float], box: Box) -> bool:
        x1, y1 = a
        x2, y2 = b
        if x1 == x2:
            x = x1
            if not (box.x < x < box.x + box.w):
                return False
            low, high = sorted([y1, y2])
            return low < box.y + box.h and high > box.y
        if y1 == y2:
            y = y1
            if not (box.y < y < box.y + box.h):
                return False
            low, high = sorted([x1, x2])
            return low < box.x + box.w and high > box.x
        return False

    def _clusters_for_node(self, node_id: str) -> List[str]:
        node = self.node_boxes.get(node_id)
        if not node:
            return []
        cx = node.x + node.w / 2
        cy = node.y + node.h / 2
        out: List[str] = []
        for cid, box in self.cluster_boxes:
            if self._point_in_box(cx, cy, box):
                out.append(cid)
        return out

    def _path_clear(self, points: List[Tuple[float, float]], src: str, dst: str) -> bool:
        src_box = self.node_boxes[src]
        dst_box = self.node_boxes[dst]
        allowed_clusters = set(self._clusters_for_node(src) + self._clusters_for_node(dst))
        blockers = list(self.node_boxes.items()) + [(cid, cbox) for cid, cbox in self.cluster_boxes]
        for p1, p2 in zip(points, points[1:]):
            for name, blocker in blockers:
                if name in {src, dst}:
                    continue
                if isinstance(name, str) and name.startswith(("stack:", "ha:")) and name in allowed_clusters:
                    continue
                if self._seg_intersects_box(p1, p2, blocker):
                    return False
            # also disallow segment interior in src/dst boxes except the first or last short stubs
            if self._seg_intersects_box(p1, p2, src_box) and p1 != points[0] and p2 != points[1]:
                return False
            if self._seg_intersects_box(p1, p2, dst_box) and p1 != points[-2] and p2 != points[-1]:
                return False
        return True

    def _pick_channel(self, primary_horizontal: bool, target: float, src: str, dst: str, s1: Tuple[float, float], d1: Tuple[float, float]) -> float:
        channels = self.row_channels if primary_horizontal else self.col_channels
        if not channels:
            return target

        ranked = sorted(channels, key=lambda c: abs(c - target))
        for base in ranked:
            use_map = self.channel_use_h if primary_horizontal else self.channel_use_v
            lane = use_map.get(base, 0)
            lane_shift = (lane % 5 - 2) * 3
            candidate = base + lane_shift
            if primary_horizontal:
                points = [s1, (s1[0], candidate), (d1[0], candidate), d1]
            else:
                points = [s1, (candidate, s1[1]), (candidate, d1[1]), d1]
            if self._path_clear(points, src, dst):
                use_map[base] = lane + 1
                return candidate
        return ranked[0]

    def _direct_stack_path(self, src_box: Box, dst_box: Box) -> List[Tuple[float, float]]:
        src_ports = self._ports(src_box)
        dst_ports = self._ports(dst_box)
        sx, sy = src_box.x + src_box.w / 2, src_box.y + src_box.h / 2
        dx, dy = dst_box.x + dst_box.w / 2, dst_box.y + dst_box.h / 2
        if abs(dx - sx) >= abs(dy - sy):
            if dx >= sx:
                return [src_ports["E"], dst_ports["W"]]
            return [src_ports["W"], dst_ports["E"]]
        if dy >= sy:
            return [src_ports["S"], dst_ports["N"]]
        return [src_ports["N"], dst_ports["S"]]

    def _route_edge(self, edge_id: str, link: Link) -> RoutedEdge | None:
        src_box = self.node_boxes.get(link.src)
        dst_box = self.node_boxes.get(link.dst)
        if not src_box or not dst_box:
            return None

        if link.media == "stacking":
            return RoutedEdge(edge_id=edge_id, link=link, points=self._direct_stack_path(src_box, dst_box))

        src_ports = self._ports(src_box)
        dst_ports = self._ports(dst_box)

        sx, sy = src_box.x + src_box.w / 2, src_box.y + src_box.h / 2
        dx, dy = dst_box.x + dst_box.w / 2, dst_box.y + dst_box.h / 2
        horizontal = abs(dx - sx) >= abs(dy - sy)

        if horizontal:
            s0 = src_ports["E"] if dx >= sx else src_ports["W"]
            d0 = dst_ports["W"] if dx >= sx else dst_ports["E"]
            stub = 14.0
            s1 = (s0[0] + (stub if dx >= sx else -stub), s0[1])
            d1 = (d0[0] + (-stub if dx >= sx else stub), d0[1])
            target_y = (s0[1] + d0[1]) / 2
            if abs(s0[1] - d0[1]) < 4:
                target_y = min(src_box.y, dst_box.y) - 26
            src_clusters = set(self._clusters_for_node(link.src))
            dst_clusters = set(self._clusters_for_node(link.dst))
            shared = src_clusters & dst_clusters
            if shared:
                cid = sorted(shared)[0]
                cbox = dict(self.cluster_boxes)[cid]
                target_y = cbox.y - 12
            ch = self._pick_channel(True, target_y, link.src, link.dst, s1, d1)
            points = [s0, s1, (s1[0], ch), (d1[0], ch), d1, d0]
        else:
            s0 = src_ports["S"] if dy >= sy else src_ports["N"]
            d0 = dst_ports["N"] if dy >= sy else dst_ports["S"]
            stub = 14.0
            s1 = (s0[0], s0[1] + (stub if dy >= sy else -stub))
            d1 = (d0[0], d0[1] + (-stub if dy >= sy else stub))
            target_x = (s0[0] + d0[0]) / 2
            if abs(s0[0] - d0[0]) < 4:
                target_x = min(src_box.x, dst_box.x) - 26
            ch = self._pick_channel(False, target_x, link.src, link.dst, s1, d1)
            points = [s0, s1, (ch, s1[1]), (ch, d1[1]), d1, d0]

        # collapse duplicate points
        cleaned: List[Tuple[float, float]] = [points[0]]
        for p in points[1:]:
            if p != cleaned[-1]:
                cleaned.append(p)

        if not self._path_clear(cleaned, link.src, link.dst):
            # fallback direct orthogonal dogleg still keeping straight lines
            cleaned = [
                (s0[0], s0[1]),
                (s0[0], d0[1]),
                (d0[0], d0[1]),
            ]
        return RoutedEdge(edge_id=edge_id, link=link, points=cleaned)

    @staticmethod
    def _box_intersects(a: Box, b: Box) -> bool:
        return not (a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y)

    def _label_segment_candidates(self, points: List[Tuple[float, float]]) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        horizontal: List[Tuple[float, Tuple[float, float], Tuple[float, float]]] = []
        vertical: List[Tuple[float, Tuple[float, float], Tuple[float, float]]] = []
        for p1, p2 in zip(points, points[1:]):
            if p1[1] == p2[1]:
                horizontal.append((abs(p2[0] - p1[0]), p1, p2))
            elif p1[0] == p2[0]:
                vertical.append((abs(p2[1] - p1[1]), p1, p2))
        ordered = sorted(horizontal, key=lambda it: it[0], reverse=True) + sorted(vertical, key=lambda it: it[0], reverse=True)
        if not ordered:
            return [(points[0], points[-1])]
        return [(p1, p2) for _, p1, p2 in ordered]

    def _place_label(self, text: str, seg: Tuple[Tuple[float, float], Tuple[float, float]]) -> Tuple[float, float, Box] | None:
        p1, p2 = seg
        mx = (p1[0] + p2[0]) / 2
        my = (p1[1] + p2[1]) / 2
        width = max(40.0, len(text) * 6.2)
        height = 12.0

        is_horizontal = p1[1] == p2[1]
        attempts: List[Tuple[float, float]] = []
        if is_horizontal:
            for slide in [0, -6, 6, -12, 12, -20, 20]:
                for nudge in [0, -2, 2, -4, 4, -10, 10, -18, 18, -28, 28, -40, 40, -56, 56, -72, 72, -86, 86]:
                    attempts.append((slide, nudge))
        else:
            for slide in [0, -6, 6, -12, 12, -20, 20]:
                for nudge in [0, -2, 2, -4, 4, -10, 10, -18, 18, -28, 28, -40, 40, -56, 56, -72, 72, -86, 86]:
                    attempts.append((nudge, slide))

        blockers = list(self.node_boxes.values()) + [box for _, box in self.cluster_boxes] + self.label_boxes
        for ox, oy in attempts:
            x = mx + ox
            y = my + oy
            box = Box(x - width / 2, y - height + 2, width, height)
            if any(self._box_intersects(box, blocker) for blocker in blockers):
                continue
            self.label_boxes.append(box)
            return x, y, box

        return None

    def _draw_node(self, device: Device) -> str:
        fill = DEVICE_FILL.get(device.device_type, "#ffffff")
        return (
            f'<rect class="node {device.device_type}" x="{device.x}" y="{device.y}" '
            f'width="{device.w}" height="{device.h}" rx="8" fill="{fill}" stroke="#1f2937"/>'
        )

    @staticmethod
    def _points_attr(points: List[Tuple[float, float]]) -> str:
        return " ".join(f"{x},{y}" for x, y in points)

    @staticmethod
    def _offset_polyline(points: List[Tuple[float, float]], offset: float, horizontal: bool) -> List[Tuple[float, float]]:
        if horizontal:
            return [(x, y + offset) for x, y in points]
        return [(x + offset, y) for x, y in points]


    def render_svg(self) -> str:
        devices = self._filter_devices()
        self.node_boxes = {}
        self.label_boxes = []
        self.channel_use_h = {}
        self.channel_use_v = {}

        content_w, content_h, _ = self._layout(devices)
        self._clusterize(devices)

        routed_edges: List[RoutedEdge] = []
        edge_idx = 0
        for link in self.topo.links:
            routed = self._route_edge(f"e{edge_idx}", link)
            edge_idx += 1
            if routed:
                routed_edges.append(routed)

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

        for routed in routed_edges:
            link = routed.link
            color = SPEED_COLORS.get(link.speed, "#334155")
            dash = MEDIA_DASH.get(link.media, "")
            style = f"stroke:{color};stroke-width:2.2;fill:none"
            if dash:
                style += f";stroke-dasharray:{dash}"
            if link.stp_blocked:
                style += ";stroke-dasharray:2,2;stroke-width:3"

            base_attr = (
                f'data-edge-id="{routed.edge_id}" data-src="{link.src}" data-dst="{link.dst}" '
                f'data-link-type="{link.link_type}" data-media="{link.media}" data-members="{link.members}" '
                f'data-direct="{"1" if link.media == "stacking" else "0"}"'
            )

            if link.link_type == "trunk" and link.members >= 2:
                seg = self._label_segment_candidates(routed.points)[0]
                horizontal = abs(seg[0][1] - seg[1][1]) < 1e-6
                p1 = self._offset_polyline(routed.points, 2.0, horizontal)
                p2 = self._offset_polyline(routed.points, -2.0, horizontal)
                parts.append(f'<polyline class="edge trunk" {base_attr} points="{self._points_attr(p1)}" style="{style}"/>')
                parts.append(f'<polyline class="edge trunk" {base_attr} points="{self._points_attr(p2)}" style="{style}"/>')
            else:
                parts.append(f'<polyline class="edge" {base_attr} points="{self._points_attr(routed.points)}" style="{style}"/>')

            label = f"{link.speed}/{link.media}"
            if link.link_type == "trunk" and link.members >= 2:
                label += f" {link.trunk_id or 'LAG'} members={link.members}"
            if link.stp_blocked:
                label += " STP blocked"

            placed = None
            chosen_seg = self._label_segment_candidates(routed.points)[0]
            for candidate_seg in self._label_segment_candidates(routed.points):
                placed = self._place_label(label, candidate_seg)
                if placed is not None:
                    chosen_seg = candidate_seg
                    break
            if placed is None:
                chosen_seg = self._label_segment_candidates(routed.points)[0]
                mx = (chosen_seg[0][0] + chosen_seg[1][0]) / 2
                my = (chosen_seg[0][1] + chosen_seg[1][1]) / 2
                lx, ly = mx, my
            else:
                lx, ly, _ = placed
            parts.append(
                f'<text class="edge-label" data-edge-id="{routed.edge_id}" data-seg="{chosen_seg[0][0]},{chosen_seg[0][1]},{chosen_seg[1][0]},{chosen_seg[1][1]}" '
                f'x="{lx}" y="{ly}" text-anchor="middle" font-size="11" fill="#111827">{label}</text>'
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
