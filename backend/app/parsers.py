from __future__ import annotations

import configparser
import io
import logging
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from openpyxl import load_workbook

from .models import CloudService, Device, ISP, Link, Topology
from .vendor_parsers import parse_aruba, parse_cisco, parse_procurve
from .vendor_parsers.common import ParsedDevice

logger = logging.getLogger(__name__)

TRUNK_PREFIXES = ("po", "port-channel", "trk", "lag", "lacp")


def _normalize_speed(raw: str) -> str:
    text = (raw or "").strip().upper().replace(" ", "")
    text = text.replace("GBPS", "G").replace("MBPS", "M")
    if text in {"1000M", "1GB", "1GIG"}:
        return "1G"
    match = re.search(r"(100|40|25|10|1)(G|M)", text)
    return f"{match.group(1)}{match.group(2)}" if match else "1G"


def _detect_vendor(content: str, filename: str) -> str:
    lowered = content.lower()
    file_lower = filename.lower()
    if "cisco ios" in lowered or "show cdp neighbors" in lowered or "_cdp_" in file_lower:
        return "cisco"
    if "procurve" in lowered or "show lldp info remote-device detail" in lowered or "show trunks" in lowered:
        return "procurve"
    if "arubaos" in lowered or "show lldp neighbors detail" in lowered or "show lacp aggregates" in lowered:
        return "aruba"
    if "show lldp info remote-device detail" in file_lower:
        return "procurve"
    if "show lldp neighbors detail" in file_lower:
        return "aruba"
    return "cisco"


def _extract_hostname(content: str, filename: str) -> str:
    patterns = [
        r"^hostname\s+(\S+)",
        r"System\s+Name\s*:\s*(\S+)",
        r"^switch\s+name\s+(\S+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
        if match:
            return match.group(1)

    stem = Path(filename).stem
    if "_show_" in stem:
        return stem.split("_show_", 1)[0]
    for sep in ("__", "-"):
        if sep in stem and "show" in stem:
            return stem.split(sep, 1)[0]
    return stem


def _parse_by_vendor(vendor: str, content: str, fallback_hostname: str) -> ParsedDevice:
    if vendor == "cisco":
        return parse_cisco(content, fallback_hostname)
    if vendor == "procurve":
        return parse_procurve(content, fallback_hostname)
    if vendor == "aruba":
        return parse_aruba(content, fallback_hostname)
    return parse_cisco(content, fallback_hostname)


def _merge_device_data(records: List[ParsedDevice]) -> ParsedDevice:
    base = records[0]
    for record in records[1:]:
        base.mgmt_ips = sorted(set(base.mgmt_ips + record.mgmt_ips))
        base.roles = sorted(set(base.roles + record.roles))
        base.stp_root = base.stp_root or record.stp_root
        base.stp_blocked_ports = sorted(set(base.stp_blocked_ports + record.stp_blocked_ports))
        base.neighbors.extend(record.neighbors)
        base.vlans = sorted(set(base.vlans + record.vlans))
        base.routes = sorted(set(base.routes + record.routes))
        base.dhcp_scopes = sorted(set(base.dhcp_scopes + record.dhcp_scopes))
        if not base.model:
            base.model = record.model
        if not base.stack_id:
            base.stack_id = record.stack_id
    return base


def _add_or_update_device(topo: Topology, parsed: ParsedDevice) -> None:
    existing = topo.devices.get(parsed.hostname)
    if existing:
        existing.mgmt_ips = sorted(set(existing.mgmt_ips + parsed.mgmt_ips))
        existing.roles = sorted(set(existing.roles + parsed.roles))
        existing.stp_root = existing.stp_root or parsed.stp_root
        if not existing.model:
            existing.model = parsed.model
        if not existing.stack_id:
            existing.stack_id = parsed.stack_id
        return

    topo.add_device(
        Device(
            id=parsed.hostname,
            hostname=parsed.hostname,
            device_type="switch",
            vendor=parsed.vendor,
            model=parsed.model,
            mgmt_ips=parsed.mgmt_ips,
            roles=parsed.roles,
            stp_root=parsed.stp_root,
            stack_id=parsed.stack_id,
        )
    )


def _dedupe_links(links: List[Link]) -> List[Link]:
    deduped: Dict[Tuple[str, str, str, str, str, str, str], Link] = {}
    for link in links:
        left, right = sorted([link.src, link.dst])
        left_port, right_port = (link.src_port, link.dst_port) if link.src == left else (link.dst_port, link.src_port)
        key = (
            left,
            right,
            left_port,
            right_port,
            link.link_type,
            link.trunk_id or "",
            f"{link.speed}:{link.media}:{'1' if link.stp_blocked else '0'}",
        )
        deduped[key] = link
    return list(deduped.values())


def _enforce_ha_redundancy(topo: Topology, firewall_names: List[str], enabled: bool, disable_override: bool) -> None:
    if not enabled or len(firewall_names) < 2 or disable_override:
        return

    firewall_set = set(firewall_names)
    additions: List[Link] = []
    for link in list(topo.links):
        if link.src in firewall_set:
            core_id, current_fw = link.dst, link.src
        elif link.dst in firewall_set:
            core_id, current_fw = link.src, link.dst
        else:
            continue

        core_device = topo.devices.get(core_id)
        if not core_device or core_device.device_type != "switch":
            continue

        for target_fw in firewall_names:
            if target_fw == current_fw:
                continue
            already_exists = any(
                {candidate.src, candidate.dst} == {core_id, target_fw}
                and candidate.link_type == link.link_type
                and candidate.media == link.media
                for candidate in topo.links + additions
            )
            if not already_exists:
                additions.append(
                    Link(
                        src=core_id,
                        dst=target_fw,
                        src_port=link.src_port,
                        dst_port=link.dst_port,
                        speed=link.speed,
                        media=link.media,
                        link_type=link.link_type,
                    )
                )

    topo.links.extend(additions)


def parse_ini(ini_bytes: bytes, topo: Topology) -> None:
    parser = configparser.ConfigParser()
    parser.read_string(ini_bytes.decode("utf-8"))

    fw_names: List[str] = []
    ha_enabled = False
    disable_core_redundancy = False

    if parser.has_section("firewall"):
        ha_enabled = parser.getboolean("firewall", "ha", fallback=False)
        fw_names = [name.strip() for name in parser.get("firewall", "nodes", fallback="FW-A,FW-B").split(",") if name.strip()]
        disable_core_redundancy = parser.getboolean("firewall", "disable_core_redundancy", fallback=False)

        for index, fw_name in enumerate(fw_names):
            topo.add_device(
                Device(
                    id=fw_name,
                    hostname=fw_name,
                    device_type="firewall",
                    model=parser.get("firewall", "model", fallback="Firewall"),
                    ha_cluster="ha-fw" if ha_enabled else None,
                    ha_role=parser.get("firewall", f"role_{index + 1}", fallback=("active" if index == 0 else "standby")),
                )
            )

        if ha_enabled and parser.getboolean("firewall", "sync_link", fallback=True) and len(fw_names) >= 2:
            topo.add_link(
                Link(
                    src=fw_names[0],
                    dst=fw_names[1],
                    speed="10G",
                    media="stacking",
                    link_type="ha-sync",
                )
            )

    topo.add_device(Device(id="Internet", hostname="Internet", device_type="internet", model="Cloud"))

    for section in parser.sections():
        if section.startswith("isp:"):
            name = section.split(":", 1)[1]
            isp = ISP(
                name=name,
                circuit_id=parser.get(section, "circuit_id", fallback=""),
                media=parser.get(section, "media", fallback="fiber").lower(),
                speed=_normalize_speed(parser.get(section, "speed", fallback="1G")),
            )
            topo.isps.append(isp)
            isp_id = f"ISP:{name}"
            topo.add_device(Device(id=isp_id, hostname=name, device_type="isp", model=isp.circuit_id))
            topo.add_link(Link(src="Internet", dst=isp_id, speed=isp.speed, media=isp.media, link_type="internet-uplink"))
            for fw in fw_names:
                topo.add_link(Link(src=isp_id, dst=fw, speed=isp.speed, media=isp.media, link_type="wan"))

        if section.startswith("cloud:"):
            cloud_name = section.split(":", 1)[1]
            provider = parser.get(section, "provider", fallback="Other")
            direct_to_firewall = parser.getboolean(section, "direct_to_firewall", fallback=False)
            cloud_id = f"CLOUD:{cloud_name}"
            topo.cloud_services.append(CloudService(name=cloud_name, provider=provider, direct_to_firewall=direct_to_firewall))
            topo.add_device(Device(id=cloud_id, hostname=cloud_name, device_type="cloud", model=provider))
            if direct_to_firewall and fw_names:
                topo.add_link(Link(src=cloud_id, dst=fw_names[0], speed="1G", media="fiber", link_type="cloud-direct"))
            else:
                topo.add_link(Link(src=cloud_id, dst="Internet", speed="1G", media="fiber", link_type="cloud-via-internet"))

    _enforce_ha_redundancy(topo, fw_names, ha_enabled, disable_core_redundancy)


def parse_excel(excel_bytes: bytes, topo: Topology) -> None:
    workbook = load_workbook(io.BytesIO(excel_bytes))

    if "devices" in workbook.sheetnames:
        worksheet = workbook["devices"]
        for row in worksheet.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            device_id = str(row[0]).strip()
            if not device_id:
                continue
            existing = topo.devices.get(device_id)
            if existing:
                continue
            topo.add_device(
                Device(
                    id=device_id,
                    hostname=device_id,
                    device_type=str(row[1] or "switch").strip().lower(),
                    model=str(row[2] or "").strip(),
                    mgmt_ips=[str(row[3]).strip()] if row[3] else [],
                )
            )

    if "links" in workbook.sheetnames:
        worksheet = workbook["links"]
        for row in worksheet.iter_rows(min_row=2, values_only=True):
            if not row or not row[0] or not row[1]:
                continue
            members = int(row[6] or 1) if len(row) > 6 else 1
            trunk_id = str(row[5]).strip() if len(row) > 5 and row[5] else None
            link_type = str(row[4] or "normal").strip().lower()
            if trunk_id and members >= 2:
                link_type = "trunk"
            topo.add_link(
                Link(
                    src=str(row[0]).strip(),
                    dst=str(row[1]).strip(),
                    speed=_normalize_speed(str(row[2] or "1G")),
                    media=str(row[3] or "copper").strip().lower(),
                    link_type=link_type,
                    trunk_id=trunk_id,
                    members=members,
                )
            )


def parse_zip(zip_bytes: bytes) -> Topology:
    topo = Topology()
    parsed_by_host: Dict[str, List[ParsedDevice]] = defaultdict(list)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        for member in archive.namelist():
            if not member.lower().endswith(".txt"):
                continue
            content = archive.read(member).decode("utf-8", errors="ignore")
            hostname = _extract_hostname(content, member)
            vendor = _detect_vendor(content, member)
            try:
                parsed = _parse_by_vendor(vendor, content, hostname)
                parsed_by_host[parsed.hostname].append(parsed)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to parse %s: %s", member, exc)

    raw_links: List[Link] = []
    for records in parsed_by_host.values():
        merged = _merge_device_data(records)
        _add_or_update_device(topo, merged)

        topo.vlan_lines.extend([f"{merged.hostname}: {line}" for line in merged.vlans])
        topo.route_lines.extend([f"{merged.hostname}: {line}" for line in merged.routes])
        topo.dhcp_lines.extend([f"{merged.hostname}: {line}" for line in merged.dhcp_scopes])

        for neighbor in merged.neighbors:
            raw_links.append(
                Link(
                    src=merged.hostname,
                    dst=neighbor.remote_host,
                    src_port=neighbor.local_intf,
                    dst_port=neighbor.remote_intf,
                    speed=_normalize_speed(neighbor.speed),
                    media=(neighbor.media or "copper").lower(),
                    link_type=(neighbor.trunk_id or "normal").lower(),
                    trunk_id=neighbor.trunk_id,
                    stp_blocked=neighbor.local_intf in merged.stp_blocked_ports,
                )
            )

    grouped: Dict[Tuple[str, str, str], List[Link]] = defaultdict(list)
    for link in raw_links:
        left, right = sorted([link.src, link.dst])
        trunk_key = (link.trunk_id or link.link_type or "normal").lower()
        grouped[(left, right, trunk_key)].append(link)

    final_links: List[Link] = []
    for (_, _, key), links in grouped.items():
        normalized = key.lower()
        if normalized.startswith(TRUNK_PREFIXES) and len(links) >= 2:
            seed = links[0]
            seed.members = len(links)
            seed.link_type = "trunk"
            seed.trunk_id = seed.trunk_id or key
            final_links.append(seed)
        else:
            for link in links:
                if normalized.startswith(TRUNK_PREFIXES):
                    link.link_type = "normal"
                    link.trunk_id = None
                final_links.append(link)

    topo.links.extend(_dedupe_links(final_links))
    topo.vlan_lines = sorted(set(topo.vlan_lines))
    topo.route_lines = sorted(set(topo.route_lines))
    topo.dhcp_lines = sorted(set(topo.dhcp_lines))
    return topo
