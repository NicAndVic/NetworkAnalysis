from __future__ import annotations

import io
import zipfile
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "samples"
SAMPLE_DATA_DIR = ROOT / "sample_data"


def cisco_device(hostname: str, neighbors: list[tuple[str, str, str, str, str, str, str | None]], stp_blocked_port: str | None = None, stack: bool = False) -> str:
    lines = [
        f"hostname {hostname}",
        "Cisco IOS XE Software",
        "-- show lldp neighbors detail --",
    ]
    for local, remote, rport, rtype, speed, media, trunk in neighbors:
        lines.extend(
            [
                f"Local Port: {local}",
                f"Neighbor: {remote}",
                f"Neighbor Port: {rport}",
                f"Type: {rtype}",
                f"Speed: {speed}",
                f"Media: {media}",
            ]
        )
        if trunk:
            lines.append(f"Trunk: {trunk}")
        lines.append("")
    lines.extend(
        [
            "-- show spanning-tree --",
            "This bridge is the root" if hostname == "CORE1" else "Spanning tree enabled",
            (f"Blocking {stp_blocked_port}" if stp_blocked_port else ""),
            "-- show etherchannel summary --",
            "Po1(SU) LACP Gi1/0/1 Gi1/0/2",
            "-- show interfaces status --",
            "Gi1/0/1 connected trunk a-full a-10000",
            "-- show vlan brief --",
            "10 Users",
            "20 Voice",
            "30 Servers",
            "-- show ip route --",
            "C 10.0.0.0/24 is directly connected",
            "S 0.0.0.0/0 via 10.0.0.1",
            "-- show ip dhcp pool --",
            "ip dhcp pool BRANCH_POOL",
        ]
    )
    if stack:
        lines.extend(["Switch 1 Provisioned", "Switch 2 Provisioned", "Stack member 1"]) 
    return "\n".join([line for line in lines if line is not None])


def procurve_device(hostname: str, neighbors: list[tuple[str, str, str, str, str, str, str | None]]) -> str:
    lines = [
        f"hostname {hostname}",
        "HP ProCurve Switch 5406zl",
        "-- show lldp info remote-device detail --",
    ]
    for local, remote, rport, rtype, speed, media, trunk in neighbors:
        lines.extend(
            [
                f"Local Port: {local}",
                f"System Name: {remote}",
                f"Port Id: {rport}",
                f"System Description: {rtype}",
                f"Speed: {speed}",
                f"Media: {media}",
            ]
        )
        if trunk:
            lines.append(f"Trunk: {trunk}")
        lines.append("")
    lines.extend(
        [
            "-- show spanning-tree --",
            "This switch is root" if hostname == "DIST1" else "Spanning tree active",
            "-- show vlan --",
            "10 Users",
            "20 Voice",
            "-- show ip route --",
            "C 172.16.10.0/24 directly connected",
        ]
    )
    return "\n".join(lines)


def aruba_device(hostname: str, neighbors: list[tuple[str, str, str, str, str, str, str | None]], blocked_port: str | None = None) -> str:
    lines = [
        f"hostname {hostname}",
        "ArubaOS-Switch",
        "-- show lldp neighbors detail --",
    ]
    for local, remote, rport, rtype, speed, media, trunk in neighbors:
        lines.extend(
            [
                f"Local Port: {local}",
                f"Neighbor: {remote}",
                f"Neighbor Port: {rport}",
                f"Type: {rtype}",
                f"Speed: {speed}",
                f"Media: {media}",
            ]
        )
        if trunk:
            lines.append(f"Trunk: {trunk}")
        lines.append("")
    lines.extend(
        [
            "-- show spanning-tree --",
            "Root this switch" if hostname == "DIST2" else "Spanning tree enabled",
            (f"BLK {blocked_port}" if blocked_port else ""),
            "-- show vlan --",
            "10 Users",
            "30 Servers",
            "-- show ip route --",
            "O 10.10.0.0/16 via 10.0.0.2",
            "-- show dhcp-server --",
            "Pool WLAN_POOL",
        ]
    )
    return "\n".join([line for line in lines if line])


def build_text_files() -> dict[str, str]:
    return {
        "CORE1.txt": cisco_device(
            "CORE1",
            [
                ("Gi1/0/1", "CORE2", "Gi1/0/1", "switch", "10G", "fiber", "Po1"),
                ("Gi1/0/2", "CORE2", "Gi1/0/2", "switch", "10G", "fiber", "Po1"),
                ("Gi1/0/3", "DIST1", "A1", "switch", "10G", "fiber", None),
                ("Gi1/0/4", "DIST2", "1/1/1", "switch", "10G", "fiber", None),
            ],
            stack=True,
        ),
        "CORE2.txt": cisco_device(
            "CORE2",
            [
                ("Gi1/0/1", "CORE1", "Gi1/0/1", "switch", "10G", "fiber", "Po1"),
                ("Gi1/0/2", "CORE1", "Gi1/0/2", "switch", "10G", "fiber", "Po1"),
                ("Gi1/0/3", "DIST1", "A2", "switch", "10G", "fiber", None),
                ("Gi1/0/4", "DIST2", "1/1/2", "switch", "10G", "fiber", None),
            ],
            stack=True,
        ),
        "DIST1.txt": procurve_device(
            "DIST1",
            [
                ("A1", "CORE1", "Gi1/0/3", "switch", "10G", "fiber", None),
                ("A2", "CORE2", "Gi1/0/3", "switch", "10G", "fiber", None),
                ("A3", "EDGE1", "1/1/1", "switch", "1G", "copper", None),
                ("A4", "EDGE2", "1/1/1", "switch", "1G", "copper", None),
                ("A5", "AP-1", "eth0", "access point", "1G", "copper", None),
            ],
        ),
        "DIST2.txt": aruba_device(
            "DIST2",
            [
                ("1/1/1", "CORE1", "Gi1/0/4", "switch", "10G", "fiber", None),
                ("1/1/2", "CORE2", "Gi1/0/4", "switch", "10G", "fiber", None),
                ("1/1/3", "EDGE3", "1/1/1", "switch", "1G", "copper", None),
                ("1/1/4", "EDGE4", "1/1/1", "switch", "1G", "copper", None),
                ("1/1/5", "AP-2", "eth0", "ap", "1G", "copper", None),
            ],
            blocked_port="1/1/3",
        ),
        "EDGE1.txt": aruba_device("EDGE1", [("1/1/1", "DIST1", "A3", "switch", "1G", "copper", None), ("1/1/2", "ACCESS1", "A1", "switch", "1G", "copper", None)]),
        "EDGE2.txt": aruba_device("EDGE2", [("1/1/1", "DIST1", "A4", "switch", "1G", "copper", None), ("1/1/2", "ACCESS2", "A1", "switch", "1G", "copper", None)]),
        "EDGE3.txt": aruba_device("EDGE3", [("1/1/1", "DIST2", "1/1/3", "switch", "1G", "copper", None), ("1/1/2", "EDGE5", "1/1/1", "switch", "1G", "copper", None)]),
        "EDGE4.txt": aruba_device("EDGE4", [("1/1/1", "DIST2", "1/1/4", "switch", "1G", "copper", None), ("1/1/2", "EDGE6", "1/1/1", "switch", "1G", "copper", None)]),
        "EDGE5.txt": aruba_device("EDGE5", [("1/1/1", "EDGE3", "1/1/2", "switch", "1G", "copper", None), ("1/1/2", "SERVER1", "eth1", "server", "1G", "copper", None), ("1/1/3", "AP-3", "eth0", "access point", "1G", "copper", None)]),
        "EDGE6.txt": aruba_device("EDGE6", [("1/1/1", "EDGE4", "1/1/2", "switch", "1G", "copper", None), ("1/1/2", "SERVER2", "eth1", "server", "1G", "copper", None), ("1/1/3", "AP-4", "eth0", "access point", "1G", "copper", None)]),
        "ACCESS1.txt": procurve_device("ACCESS1", [("A1", "EDGE1", "1/1/2", "switch", "1G", "copper", None)]),
        "ACCESS2.txt": procurve_device("ACCESS2", [("A1", "EDGE2", "1/1/2", "switch", "1G", "copper", None)]),
    }


def write_sample_ini(path: Path) -> None:
    path.write_text(
        """[firewall]
ha = true
nodes = FW-A, FW-B
model = PA-3220
sync_link = true
disable_core_redundancy = false

[isp:PrimaryISP]
circuit_id = PRI-100
speed = 10G
media = fiber

[isp:BackupISP]
circuit_id = BAK-010
speed = 1G
media = copper

[cloud:AWS-Prod]
provider = AWS
direct_to_firewall = false

[cloud:Azure-DR]
provider = Azure
direct_to_firewall = false

[cloud:Other-SaaS]
provider = Other
direct_to_firewall = false
"""
    )


def write_sample_excel(path: Path) -> None:
    workbook = Workbook()
    ws_devices = workbook.active
    ws_devices.title = "devices"
    ws_devices.append(["id", "type", "model", "mgmt_ip"])
    ws_devices.append(["SERVER1", "server", "Linux", "10.10.30.11"])
    ws_devices.append(["SERVER2", "server", "Windows", "10.10.30.12"])
    ws_devices.append(["AP-1", "ap", "Aruba-AP", "10.10.40.21"])
    ws_devices.append(["AP-2", "ap", "Aruba-AP", "10.10.40.22"])
    ws_devices.append(["AP-3", "ap", "Aruba-AP", "10.10.40.23"])
    ws_devices.append(["AP-4", "ap", "Aruba-AP", "10.10.40.24"])

    ws_links = workbook.create_sheet("links")
    ws_links.append(["src", "dst", "speed", "media", "link_type", "trunk_id", "members"])
    ws_links.append(["EDGE5", "SERVER1", "1G", "copper", "normal", "", 1])
    ws_links.append(["EDGE6", "SERVER2", "1G", "copper", "normal", "", 1])

    workbook.save(path)


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    text_files = build_text_files()

    for out_dir in (SAMPLES_DIR, SAMPLE_DATA_DIR):
        for name, content in text_files.items():
            (out_dir / name).write_text(content)

    ini_path = SAMPLES_DIR / "sample_edge.ini"
    xlsx_path = SAMPLES_DIR / "sample_manual.xlsx"
    zip_path = SAMPLES_DIR / "sample_bundle.zip"

    write_sample_ini(ini_path)
    write_sample_excel(xlsx_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in text_files.items():
            archive.writestr(name, content)

    # compatibility mirror
    (SAMPLE_DATA_DIR / "edge_template.ini").write_text(ini_path.read_text())
    (SAMPLE_DATA_DIR / "sample_bundle.zip").write_bytes(zip_path.read_bytes())
    (SAMPLE_DATA_DIR / "sample_manual.xlsx").write_bytes(xlsx_path.read_bytes())

    print(f"Wrote sample artifacts in {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
