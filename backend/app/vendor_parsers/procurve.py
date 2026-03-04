from __future__ import annotations

import re

from .common import NeighborRecord, ParsedDevice, detect_device_type, normalize_interface_name, normalize_speed, parse_blocks, should_keep_neighbor


def parse_procurve(content: str, fallback_hostname: str) -> ParsedDevice:
    blocks = parse_blocks(content)
    raw = blocks.get("raw", content)
    hostname = fallback_hostname
    if m := re.search(r"^hostname\s+(\S+)", raw, re.MULTILINE | re.IGNORECASE):
        hostname = m.group(1)
    elif m := re.search(r"System\s+Name\s*:\s*(\S+)", content, re.IGNORECASE):
        hostname = m.group(1)

    model = ""
    if m := re.search(r"HP\s+([0-9A-Za-z\-]+)\s+Switch", content):
        model = m.group(1)

    mgmt = sorted(set(re.findall(r"\b(?:10|172|192)\.\d+\.\d+\.\d+\b", content)))[:3]
    roles = ["L3"] if re.search(r"ip routing", raw, re.IGNORECASE) else []
    stp_root = bool(re.search(r"This switch is root", blocks.get("show spanning-tree", ""), re.IGNORECASE))
    blocked = re.findall(r"(?:BLK|Blocking)\s+(\S+)", blocks.get("show spanning-tree", ""), re.IGNORECASE)

    neigh_text = blocks.get("show lldp info remote-device detail", "")
    pattern = re.compile(
        r"Local\s+Port\s*:\s*(\S+).*?System\s+Name\s*:\s*(\S+).*?Port\s+Id\s*:\s*(\S+).*?System\s+Description\s*:\s*([^\n]+).*?Speed\s*:\s*([^\n]+).*?Media\s*:\s*([^\n]+)(?:.*?Trunk\s*:\s*(\S+))?",
        re.IGNORECASE | re.DOTALL,
    )
    neighbors = []
    for m in pattern.finditer(neigh_text):
        local, remote, rport, rtype_raw, speed, media, trunk = m.groups()
        rtype = detect_device_type(rtype_raw)
        if not should_keep_neighbor(rtype):
            continue
        neighbors.append(
            NeighborRecord(
                local_intf=normalize_interface_name(local),
                remote_host=remote,
                remote_intf=normalize_interface_name(rport),
                remote_type=rtype,
                speed=normalize_speed(speed),
                media=media.strip().lower(),
                trunk_id=trunk,
            )
        )

    vlans = [f"VLAN {vid} {name}" for vid, name in re.findall(r"^\s*(\d+)\s+([\w\-]+)", blocks.get("show vlan", ""), re.MULTILINE)]
    routes = [f"{p} {r}" for p, r in re.findall(r"^(S|C)\s+([^\n]+)", blocks.get("show ip route", ""), re.MULTILINE)]

    return ParsedDevice(
        hostname=hostname,
        vendor="hp procurve",
        model=model,
        mgmt_ips=mgmt,
        roles=roles,
        stp_root=stp_root,
        stp_blocked_ports=[normalize_interface_name(x) for x in blocked],
        neighbors=neighbors,
        vlans=vlans,
        routes=routes,
    )
