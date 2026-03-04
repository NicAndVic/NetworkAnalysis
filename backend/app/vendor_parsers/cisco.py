from __future__ import annotations

import re

from .common import NeighborRecord, ParsedDevice, detect_device_type, normalize_interface_name, normalize_speed, parse_blocks, should_keep_neighbor


def parse_cisco(content: str, fallback_hostname: str) -> ParsedDevice:
    blocks = parse_blocks(content)
    raw = blocks.get("raw", content)
    hostname = fallback_hostname
    if m := re.search(r"^hostname\s+(\S+)", raw, re.MULTILINE | re.IGNORECASE):
        hostname = m.group(1)

    model = ""
    if m := re.search(r"Model\s+number\s*:\s*(\S+)", content, re.IGNORECASE):
        model = m.group(1)

    mgmt = sorted(set(re.findall(r"\b(?:10|172|192)\.\d+\.\d+\.\d+\b", content)))[:3]
    roles = []
    if re.search(r"\bip routing\b", raw, re.IGNORECASE):
        roles.append("L3")
    if re.search(r"\bip dhcp pool\b", content, re.IGNORECASE):
        roles.append("DHCP")

    stp_root = bool(re.search(r"this bridge is the root", blocks.get("show spanning-tree", ""), re.IGNORECASE))
    blocked = re.findall(r"(?:BLK|Blocking)\s+(\S+)", blocks.get("show spanning-tree", ""), re.IGNORECASE)

    stack_id = "core-stack" if re.search(r"stack member|switch\s+\d+\s+provisioned", content, re.IGNORECASE) and hostname.startswith("CORE") else None

    neigh_text = blocks.get("show lldp neighbors detail", "") + "\n" + blocks.get("show cdp neighbors detail", "")
    neighbors = []
    pattern = re.compile(
        r"Local\s+Port\s*:\s*(\S+).*?Neighbor\s*:\s*(\S+).*?Neighbor\s+Port\s*:\s*(\S+).*?Type\s*:\s*([^\n]+).*?Speed\s*:\s*([^\n]+).*?Media\s*:\s*([^\n]+)(?:.*?Trunk\s*:\s*(\S+))?",
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(neigh_text):
        local, remote, rport, rtype_raw, speed, media, trunk = m.groups()
        rtype = detect_device_type(rtype_raw)
        if not should_keep_neighbor(rtype):
            continue
        neighbors.append(
            NeighborRecord(
                local_intf=normalize_interface_name(local),
                remote_host=remote.strip(),
                remote_intf=normalize_interface_name(rport),
                remote_type=rtype,
                speed=normalize_speed(speed),
                media=media.strip().lower(),
                trunk_id=trunk,
            )
        )

    vlans = [f"VLAN {vid} {name}" for vid, name in re.findall(r"^\s*(\d+)\s+([\w\-]+)", blocks.get("show vlan brief", "") + "\n" + blocks.get("show vlan", ""), re.MULTILINE)]
    routes = [f"{p} {r}" for p, r in re.findall(r"^(S|O|C|L)\s+([^\n]+)", blocks.get("show ip route", ""), re.MULTILINE)]
    dhcp = [f"Pool {x}" for x in re.findall(r"ip dhcp pool\s+(\S+)", content, re.IGNORECASE)]

    return ParsedDevice(
        hostname=hostname,
        vendor="cisco",
        model=model,
        mgmt_ips=mgmt,
        roles=sorted(set(roles)),
        stp_root=stp_root,
        stp_blocked_ports=[normalize_interface_name(x) for x in blocked],
        stack_id=stack_id,
        neighbors=neighbors,
        vlans=vlans,
        routes=routes,
        dhcp_scopes=dhcp,
    )
