from __future__ import annotations

import configparser
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from openpyxl import load_workbook

from .models import CloudService, Device, ISP, Link, Topology

DEVICE_ALLOWED = {"switch", "firewall", "router", "server", "ap"}


def _parse_txt_device(content: str, fallback_id: str) -> Tuple[Device, List[Link], List[str], List[str], List[str]]:
    hostname = fallback_id
    vendor = "unknown"
    model = ""
    mgmt_ips: List[str] = []
    device_type = "switch"
    roles: List[str] = []
    stp_root = False
    stack_id = None
    links: List[Link] = []
    vlan_lines: List[str] = []
    dhcp_lines: List[str] = []
    route_lines: List[str] = []

    for line in content.splitlines():
        if m := re.match(r"HOSTNAME:\s*(.+)", line):
            hostname = m.group(1).strip()
        elif m := re.match(r"VENDOR:\s*(.+)", line):
            vendor = m.group(1).strip().lower()
        elif m := re.match(r"MODEL:\s*(.+)", line):
            model = m.group(1).strip()
        elif m := re.match(r"MGMT_IP:\s*(.+)", line):
            mgmt_ips.append(m.group(1).strip())
        elif m := re.match(r"DEVICE_TYPE:\s*(.+)", line):
            dt = m.group(1).strip().lower()
            if dt in DEVICE_ALLOWED:
                device_type = dt
        elif m := re.match(r"ROLE:\s*(.+)", line):
            roles.extend([p.strip() for p in m.group(1).split(",") if p.strip()])
        elif "STP_ROOT: yes" in line.lower():
            stp_root = True
        elif m := re.match(r"STACK_ID:\s*(.+)", line):
            stack_id = m.group(1).strip()
        elif m := re.match(
            r"NEIGHBOR:\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+)",
            line,
        ):
            remote, local_p, remote_p, speed, media, ltype, remote_type = [v.strip() for v in m.groups()]
            if remote_type.lower() not in DEVICE_ALLOWED:
                continue
            links.append(
                Link(
                    src=hostname,
                    dst=remote,
                    src_port=local_p,
                    dst_port=remote_p,
                    speed=speed,
                    media=media.lower(),
                    link_type=ltype.lower(),
                    trunk_id=(ltype if ltype.lower().startswith(("po", "trk")) else None),
                )
            )
        elif m := re.match(r"STP_BLOCKED:\s*(.+)", line):
            blocked_ports = {p.strip() for p in m.group(1).split(",")}
            for lk in links:
                if lk.src_port in blocked_ports:
                    lk.stp_blocked = True
        elif m := re.match(r"VLAN:\s*(.+)", line):
            vlan_lines.append(f"{hostname}: {m.group(1).strip()}")
        elif m := re.match(r"DHCP_SCOPE:\s*(.+)", line):
            dhcp_lines.append(f"{hostname}: {m.group(1).strip()}")
        elif m := re.match(r"ROUTE:\s*(.+)", line):
            route_lines.append(f"{hostname}: {m.group(1).strip()}")

    device = Device(
        id=hostname,
        hostname=hostname,
        device_type=device_type,
        vendor=vendor,
        model=model,
        mgmt_ips=mgmt_ips,
        roles=roles,
        stp_root=stp_root,
        stack_id=stack_id,
    )
    return device, links, vlan_lines, dhcp_lines, route_lines


def parse_ini(ini_bytes: bytes, topo: Topology) -> None:
    parser = configparser.ConfigParser()
    parser.read_string(ini_bytes.decode("utf-8"))
    if parser.has_section("firewall"):
        ha = parser.get("firewall", "ha", fallback="false").lower() == "true"
        names = [v.strip() for v in parser.get("firewall", "nodes", fallback="FW-A,FW-B").split(",")]
        for idx, name in enumerate(names):
            d = Device(
                id=name,
                hostname=name,
                device_type="firewall",
                model=parser.get("firewall", "model", fallback="Firewall"),
                ha_cluster="ha-fw" if ha else None,
                ha_role="active" if idx == 0 else "standby",
            )
            topo.add_device(d)
        if ha and parser.get("firewall", "sync_link", fallback="true").lower() == "true" and len(names) > 1:
            topo.add_link(Link(src=names[0], dst=names[1], speed="10G", media="stacking", link_type="ha-sync"))

    for sec in parser.sections():
        if sec.startswith("isp:"):
            topo.isps.append(
                ISP(
                    name=sec.split(":", 1)[1],
                    circuit_id=parser.get(sec, "circuit_id", fallback=""),
                    media=parser.get(sec, "media", fallback="fiber"),
                    speed=parser.get(sec, "speed", fallback="1G"),
                )
            )
        if sec.startswith("cloud:"):
            provider = parser.get(sec, "provider", fallback="Other")
            topo.cloud_services.append(
                CloudService(
                    name=sec.split(":", 1)[1],
                    provider=provider,
                    direct_to_firewall=parser.get(sec, "direct_to_firewall", fallback="false").lower() == "true",
                )
            )


def parse_excel(excel_bytes: bytes, topo: Topology) -> None:
    wb = load_workbook(io.BytesIO(excel_bytes))
    if "devices" in wb.sheetnames:
        ws = wb["devices"]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[0]:
                continue
            device = Device(
                id=str(row[0]),
                hostname=str(row[0]),
                device_type=str(row[1] or "switch").lower(),
                model=str(row[2] or ""),
                mgmt_ips=[str(row[3])] if row[3] else [],
            )
            topo.devices.setdefault(device.id, device)
    if "links" in wb.sheetnames:
        ws = wb["links"]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[0] or not row[1]:
                continue
            topo.add_link(
                Link(
                    src=str(row[0]),
                    dst=str(row[1]),
                    speed=str(row[2] or "1G"),
                    media=str(row[3] or "copper").lower(),
                    link_type=str(row[4] or "normal").lower(),
                )
            )


def parse_zip(zip_bytes: bytes) -> Topology:
    topo = Topology()
    raw_links: List[Link] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for member in zf.namelist():
            if not member.endswith(".txt"):
                continue
            content = zf.read(member).decode("utf-8", errors="ignore")
            device, links, vlans, dhcp, routes = _parse_txt_device(content, Path(member).stem)
            topo.add_device(device)
            raw_links.extend(links)
            topo.vlan_lines.extend(vlans)
            topo.dhcp_lines.extend(dhcp)
            topo.route_lines.extend(routes)

    grouped: Dict[Tuple[str, str, str], List[Link]] = defaultdict(list)
    for lk in raw_links:
        a, b = sorted([lk.src, lk.dst])
        grouped[(a, b, lk.link_type)].append(lk)
    for (_, _, ltype), links in grouped.items():
        if ltype.startswith(("po", "trk")) and len(links) >= 2:
            seed = links[0]
            seed.members = len(links)
            seed.link_type = "trunk"
            topo.add_link(seed)
        else:
            for lk in links:
                lk.link_type = "normal" if lk.link_type.startswith(("po", "trk")) else lk.link_type
                topo.add_link(lk)
    return topo
