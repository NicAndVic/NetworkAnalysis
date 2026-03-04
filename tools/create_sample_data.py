from pathlib import Path
import shutil
import zipfile
from openpyxl import Workbook

root = Path(__file__).resolve().parents[1]
sample_data = root / "sample_data"
samples = root / "samples"
for base in [sample_data, samples]:
    (base / "generated").mkdir(parents=True, exist_ok=True)

switches = [
    ("CORE1", "Cisco IOS-XE", "C9500", "10.0.0.1", "core-stack", "cisco"),
    ("CORE2", "Cisco IOS-XE", "C9500", "10.0.0.2", "core-stack", "cisco"),
    ("DIST1", "ArubaOS-S", "6300", "10.0.1.1", None, "aruba"),
    ("DIST2", "ArubaOS-S", "6300", "10.0.1.2", None, "aruba"),
    ("EDGE1", "HP ProCurve", "2930F", "10.0.2.1", None, "procurve"),
    ("EDGE2", "HP ProCurve", "2930F", "10.0.2.2", None, "procurve"),
    ("EDGE3", "Cisco IOS", "9200", "10.0.2.3", None, "cisco"),
    ("EDGE4", "Cisco IOS", "9200", "10.0.2.4", None, "cisco"),
    ("EDGE5", "ArubaOS-S", "6100", "10.0.2.5", None, "aruba"),
    ("EDGE6", "ArubaOS-S", "6100", "10.0.2.6", None, "aruba"),
    ("ACCESS1", "Cisco IOS", "2960", "10.0.3.1", None, "cisco"),
    ("ACCESS2", "Cisco IOS", "2960", "10.0.3.2", None, "cisco"),
]

neighbors = {
    "CORE1": [("Te1/1", "CORE2", "Te1/1", "switch", "40G", "stacking", "stack"), ("Te1/2", "DIST1", "1/1/1", "switch", "10G", "fiber", "Po10"), ("Te1/3", "DIST1", "1/1/2", "switch", "10G", "fiber", "Po10"), ("Te1/4", "DIST2", "1/1/1", "switch", "10G", "fiber", "Po20"), ("Te1/5", "DIST2", "1/1/2", "switch", "10G", "fiber", "Po20"), ("Te1/10", "FW-A", "port1", "firewall", "10G", "fiber", "normal")],
    "CORE2": [("Te1/1", "CORE1", "Te1/1", "switch", "40G", "stacking", "stack"), ("Te1/2", "DIST1", "1/1/3", "switch", "10G", "fiber", "Po11"), ("Te1/3", "DIST1", "1/1/4", "switch", "10G", "fiber", "Po11"), ("Te1/4", "DIST2", "1/1/3", "switch", "10G", "fiber", "Po21"), ("Te1/5", "DIST2", "1/1/4", "switch", "10G", "fiber", "Po21"), ("Te1/10", "FW-B", "port1", "firewall", "10G", "fiber", "normal")],
    "DIST1": [("1/1/5", "EDGE1", "1", "switch", "1G", "copper", "normal"), ("1/1/6", "EDGE2", "1", "switch", "1G", "copper", "normal"), ("1/1/7", "ACCESS1", "1", "switch", "1G", "copper", "normal")],
    "DIST2": [("1/1/5", "EDGE3", "1", "switch", "1G", "copper", "normal"), ("1/1/6", "EDGE4", "1", "switch", "1G", "copper", "normal"), ("1/1/7", "ACCESS2", "1", "switch", "1G", "copper", "normal")],
    "EDGE1": [("2", "EDGE5", "1", "switch", "1G", "dac", "normal"), ("3", "AP1", "eth0", "ap", "1G", "copper", "normal")],
    "EDGE2": [("2", "EDGE6", "1", "switch", "1G", "dac", "normal"), ("3", "AP2", "eth0", "ap", "1G", "copper", "normal")],
    "EDGE3": [("3", "AP3", "eth0", "ap", "1G", "copper", "normal")],
    "EDGE4": [("3", "AP4", "eth0", "ap", "1G", "copper", "normal")],
    "EDGE5": [], "EDGE6": [], "ACCESS1": [], "ACCESS2": [],
}

for name, os_name, model, ip, stack, vendor in switches:
    text = [f"{os_name} Software", f"hostname {name}", f"Model number: {model}", f"Management Address: {ip}"]
    if stack:
        text.append("Stack member 1")
    text += ["-- show running-config --", f"hostname {name}", "ip routing"]
    if name.startswith("CORE"):
        text.append("ip dhcp pool USERS")
    if vendor == "procurve":
        text.append("-- show lldp info remote-device detail --")
    else:
        text.append("-- show lldp neighbors detail --")
    for local, remote, rport, rtype, speed, media, trunk in neighbors[name]:
        text += [
            f"Local Port: {local}",
            f"Neighbor: {remote}" if vendor != "procurve" else f"System Name: {remote}",
            f"Neighbor Port: {rport}" if vendor != "procurve" else f"Port Id: {rport}",
            f"Type: {rtype}" if vendor != "procurve" else f"System Description: {rtype}",
            f"Speed: {speed}",
            f"Media: {media}",
            f"Trunk: {trunk}",
            "",
        ]
    text.append("-- show spanning-tree --")
    if name in {"CORE1", "CORE2"}:
        text.append("This bridge is the root" if vendor == "cisco" else "Root this switch")
    if name == "DIST1":
        text.append("BLK 1/1/6")
    text += ["-- show vlan --", "10 Users", "20 Voice", "30 Servers", "-- show ip route --", "C 10.10.10.0/24 is directly connected", "S 0.0.0.0/0 via 10.0.0.254"]
    if name.startswith("CORE"):
        text += ["-- show ip dhcp pool --", "ip dhcp pool USERS"]

    for base in [sample_data, samples]:
        (base / f"{name}.txt").write_text("\n".join(text))

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
(sample_data / "edge_template.ini").write_text(ini)
(samples / "sample_edge.ini").write_text(ini)

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
wb.save(sample_data / "manual_template.xlsx")
shutil.copy2(sample_data / "manual_template.xlsx", samples / "sample_manual.xlsx")

with zipfile.ZipFile(sample_data / "switch_exports.zip", "w", zipfile.ZIP_DEFLATED) as zf:
    for txt in sorted(sample_data.glob("*.txt")):
        zf.write(txt, txt.name)
with zipfile.ZipFile(samples / "sample_bundle.zip", "w", zipfile.ZIP_DEFLATED) as zf:
    for txt in sorted(samples.glob("*.txt")):
        zf.write(txt, txt.name)

print("sample data created")
