from pathlib import Path
import zipfile
from openpyxl import Workbook

root = Path(__file__).resolve().parents[1] / "sample_data"
(root / "generated").mkdir(parents=True, exist_ok=True)

switches = [
    ("CORE1", "Cisco IOS-XE", "C9500", "10.0.0.1", "core-stack"),
    ("CORE2", "Cisco IOS-XE", "C9500", "10.0.0.2", "core-stack"),
    ("DIST1", "ArubaOS-S", "6300", "10.0.1.1", None),
    ("DIST2", "ArubaOS-S", "6300", "10.0.1.2", None),
    ("EDGE1", "HP ProCurve", "2930F", "10.0.2.1", None),
    ("EDGE2", "HP ProCurve", "2930F", "10.0.2.2", None),
    ("EDGE3", "Cisco IOS", "9200", "10.0.2.3", None),
    ("EDGE4", "Cisco IOS", "9200", "10.0.2.4", None),
    ("EDGE5", "ArubaOS-S", "6100", "10.0.2.5", None),
    ("EDGE6", "ArubaOS-S", "6100", "10.0.2.6", None),
    ("ACCESS1", "Cisco IOS", "2960", "10.0.3.1", None),
    ("ACCESS2", "Cisco IOS", "2960", "10.0.3.2", None),
]

neighbors = {
    "CORE1": [
        ("Te1/1", "CORE2", "Te1/1", "switch", "40G", "stacking", "stack"),
        ("Te1/2", "DIST1", "1/1/1", "switch", "10G", "fiber", "Po10"),
        ("Te1/3", "DIST1", "1/1/2", "switch", "10G", "fiber", "Po10"),
        ("Te1/4", "DIST2", "1/1/1", "switch", "10G", "fiber", "Po20"),
        ("Te1/5", "DIST2", "1/1/2", "switch", "10G", "fiber", "Po20"),
        ("Te1/10", "FW-A", "port1", "firewall", "10G", "fiber", "normal"),
        ("Te1/11", "FW-B", "port1", "firewall", "10G", "fiber", "normal"),
    ],
    "CORE2": [
        ("Te1/1", "CORE1", "Te1/1", "switch", "40G", "stacking", "stack"),
        ("Te1/2", "DIST1", "1/1/3", "switch", "10G", "fiber", "Po11"),
        ("Te1/3", "DIST1", "1/1/4", "switch", "10G", "fiber", "Po11"),
        ("Te1/4", "DIST2", "1/1/3", "switch", "10G", "fiber", "Po21"),
        ("Te1/5", "DIST2", "1/1/4", "switch", "10G", "fiber", "Po21"),
        ("Te1/10", "FW-A", "port2", "firewall", "10G", "fiber", "normal"),
        ("Te1/11", "FW-B", "port2", "firewall", "10G", "fiber", "normal"),
    ],
    "DIST1": [("1/1/5", "EDGE1", "1", "switch", "1G", "copper", "normal"), ("1/1/6", "EDGE2", "1", "switch", "1G", "copper", "normal"), ("1/1/7", "ACCESS1", "1", "switch", "1G", "copper", "normal")],
    "DIST2": [("1/1/5", "EDGE3", "1", "switch", "1G", "copper", "normal"), ("1/1/6", "EDGE4", "1", "switch", "1G", "copper", "normal"), ("1/1/7", "ACCESS2", "1", "switch", "1G", "copper", "normal")],
    "EDGE1": [("2", "EDGE5", "1", "switch", "1G", "dac", "normal"), ("3", "AP1", "eth0", "ap", "1G", "copper", "normal")],
    "EDGE2": [("2", "EDGE6", "1", "switch", "1G", "dac", "normal"), ("3", "AP2", "eth0", "ap", "1G", "copper", "normal")],
    "EDGE3": [("3", "AP3", "eth0", "ap", "1G", "copper", "normal")],
    "EDGE4": [("3", "AP4", "eth0", "ap", "1G", "copper", "normal")],
    "EDGE5": [], "EDGE6": [], "ACCESS1": [], "ACCESS2": [],
}

for name, os_name, model, ip, stack in switches:
    text = []
    text.append(f"{os_name} Software")
    text.append(f"hostname {name}")
    text.append(f"Model number: {model}")
    text.append(f"Management Address: {ip}")
    if stack:
        text.append("Stack member 1")
    text.append("-- show running-config --")
    text.append(f"hostname {name}")
    text.append("ip routing")
    if name.startswith("CORE"):
        text.append("ip dhcp pool USERS")
    text.append("-- show lldp neighbors detail --")
    for local, remote, rport, rtype, speed, media, trunk in neighbors[name]:
        text.append(f"Local Port: {local}")
        text.append(f"Neighbor: {remote}")
        text.append(f"Neighbor Port: {rport}")
        text.append(f"Type: {rtype}")
        text.append(f"Speed: {speed}")
        text.append(f"Media: {media}")
        text.append(f"Trunk: {trunk}")
        text.append("")
    text.append("-- show spanning-tree --")
    if name in {"CORE1", "CORE2"}:
        text.append("This bridge is the root")
    if name == "DIST1":
        text.append("BLK 1/1/6")
    text.append("-- show vlan --")
    text.append("10 Users")
    text.append("20 Voice")
    text.append("30 Servers")
    text.append("-- show ip route --")
    text.append("C 10.10.10.0/24 is directly connected")
    text.append("S 0.0.0.0/0 via 10.0.0.254")
    if name.startswith("CORE"):
        text.append("-- show ip dhcp pool --")
        text.append("Pool USERS 10.10.10.0/24")
    (root / f"{name}.txt").write_text("\n".join(text))

ini = """[firewall]
ha=true
nodes=FW-A,FW-B
model=Fortigate-200F
role_1=active
role_2=standby
sync_link=true

[isp:ISP-A]
circuit_id=CIR-100
media=fiber
speed=10G

[isp:ISP-B]
circuit_id=CIR-200
media=fiber
speed=1G

[cloud:AWS-Prod]
provider=AWS
direct_to_firewall=false

[cloud:Azure-DR]
provider=Azure
direct_to_firewall=false

[cloud:Other-SaaS]
provider=Other
direct_to_firewall=false
"""
(root / "edge_template.ini").write_text(ini)

wb = Workbook()
ws = wb.active
ws.title = "devices"
ws.append(["id", "type", "model", "mgmt_ip"])
ws.append(["SRV1", "server", "Linux", "10.0.10.11"])
ws.append(["SRV2", "server", "Windows", "10.0.10.12"])
ws.append(["AP1", "ap", "Ubiquiti U6", "10.0.20.11"])
ws.append(["AP2", "ap", "Ubiquiti U6", "10.0.20.12"])
ws.append(["AP3", "ap", "Aruba AP", "10.0.20.13"])
ws.append(["AP4", "ap", "Aruba AP", "10.0.20.14"])
ws2 = wb.create_sheet("links")
ws2.append(["src", "dst", "speed", "media", "type"])
ws2.append(["EDGE5", "SRV1", "1G", "copper", "normal"])
ws2.append(["EDGE6", "SRV2", "1G", "copper", "normal"])
wb.save(root / "manual_template.xlsx")

with zipfile.ZipFile(root / "switch_exports.zip", "w", zipfile.ZIP_DEFLATED) as zf:
    for txt in sorted(root.glob("*.txt")):
        zf.write(txt, txt.name)

print("sample data created")
