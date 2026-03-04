from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


ALLOWED_TYPES = {"switch", "firewall", "router", "server", "ap"}
DROP_TYPES = {"phone", "printer", "camera", "workstation", "endpoint", "unknown"}


@dataclass
class NeighborRecord:
    local_intf: str
    remote_host: str
    remote_intf: str
    remote_type: str
    speed: str = "1G"
    media: str = "copper"
    trunk_id: Optional[str] = None


@dataclass
class ParsedDevice:
    hostname: str
    vendor: str
    model: str = ""
    mgmt_ips: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    stp_root: bool = False
    stp_blocked_ports: List[str] = field(default_factory=list)
    stack_id: Optional[str] = None
    neighbors: List[NeighborRecord] = field(default_factory=list)
    vlans: List[str] = field(default_factory=list)
    routes: List[str] = field(default_factory=list)
    dhcp_scopes: List[str] = field(default_factory=list)


def normalize_speed(raw: str) -> str:
    t = (raw or "").upper().replace(" ", "")
    t = t.replace("GBPS", "G").replace("MBPS", "M")
    if t in {"1000M", "1GB", "1GIG"}:
        return "1G"
    m = re.search(r"(10|25|40|100|1|100)(G|M)", t)
    return f"{m.group(1)}{m.group(2)}" if m else "1G"


def normalize_interface_name(name: str) -> str:
    n = (name or "").strip()
    n = n.replace("TenGigabitEthernet", "Te").replace("GigabitEthernet", "Gi")
    n = n.replace("Port-channel", "Po").replace("port-channel", "Po")
    n = n.replace("Ethernet", "Eth")
    n = re.sub(r"\s+", "", n)
    return n


def detect_device_type(platform: str) -> str:
    p = (platform or "").lower()
    if any(x in p for x in ["firewall", "forti", "palo"]):
        return "firewall"
    if any(x in p for x in ["router", "isr"]):
        return "router"
    if any(x in p for x in ["server", "esxi", "linux", "windows"]):
        return "server"
    if any(x in p for x in ["ap", "access point", "ubiquiti", "aruba ap"]):
        return "ap"
    if any(x in p for x in ["switch", "cisco", "procurve", "aruba", "stack"]):
        return "switch"
    return "unknown"


def should_keep_neighbor(remote_type: str) -> bool:
    t = (remote_type or "").lower().strip()
    if t in DROP_TYPES:
        return False
    return t in ALLOWED_TYPES


def parse_blocks(content: str) -> Dict[str, str]:
    sections: Dict[str, List[str]] = {"raw": []}
    current = "raw"
    for line in content.splitlines():
        s = line.strip().lower()
        if s.startswith("-- show ") and s.endswith(" --"):
            current = s[3:-3].strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v) for k, v in sections.items()}
