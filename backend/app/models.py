from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Device:
    id: str
    hostname: str
    device_type: str
    vendor: str = "unknown"
    model: str = ""
    mgmt_ips: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    stp_root: bool = False
    stack_id: Optional[str] = None
    ha_cluster: Optional[str] = None
    ha_role: Optional[str] = None
    x: float = 0.0
    y: float = 0.0
    w: float = 180.0
    h: float = 82.0


@dataclass
class Link:
    src: str
    dst: str
    src_port: str = ""
    dst_port: str = ""
    speed: str = "1G"
    media: str = "copper"
    link_type: str = "normal"
    stp_blocked: bool = False
    trunk_id: Optional[str] = None
    members: int = 1
    label_pos: Optional[Tuple[float, float]] = None


@dataclass
class ISP:
    name: str
    circuit_id: str
    media: str
    speed: str


@dataclass
class CloudService:
    name: str
    provider: str
    direct_to_firewall: bool = False


@dataclass
class Topology:
    devices: Dict[str, Device] = field(default_factory=dict)
    links: List[Link] = field(default_factory=list)
    isps: List[ISP] = field(default_factory=list)
    cloud_services: List[CloudService] = field(default_factory=list)
    vlan_lines: List[str] = field(default_factory=list)
    dhcp_lines: List[str] = field(default_factory=list)
    route_lines: List[str] = field(default_factory=list)
    title: str = "Network Diagram Generator"

    def add_device(self, device: Device) -> None:
        self.devices[device.id] = device

    def add_link(self, link: Link) -> None:
        if link.src == link.dst:
            return
        self.links.append(link)
