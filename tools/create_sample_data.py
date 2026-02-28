from pathlib import Path
import zipfile
from openpyxl import Workbook

root = Path(__file__).resolve().parents[1] / "sample_data"
root.mkdir(exist_ok=True)

switches = [
    ("CORE1","Cisco","C9500","10.0.0.1","core-stack"),
    ("CORE2","Cisco","C9500","10.0.0.2","core-stack"),
    ("DIST1","Aruba","6300","10.0.1.1",None),
    ("DIST2","Aruba","6300","10.0.1.2",None),
    ("EDGE1","HP ProCurve","2930F","10.0.2.1",None),
    ("EDGE2","HP ProCurve","2930F","10.0.2.2",None),
    ("EDGE3","Cisco","9200","10.0.2.3",None),
    ("EDGE4","Cisco","9200","10.0.2.4",None),
    ("EDGE5","Aruba","6100","10.0.2.5",None),
    ("EDGE6","Aruba","6100","10.0.2.6",None),
    ("ACCESS1","Cisco","2960","10.0.3.1",None),
    ("ACCESS2","Cisco","2960","10.0.3.2",None),
]

neighbors = {
    "CORE1":[("CORE2","Te1/1","Te1/1","40G","stacking","stack","switch"),("DIST1","Te1/2","1/1/1","10G","fiber","Po10","switch"),("DIST1","Te1/3","1/1/2","10G","fiber","Po10","switch"),("DIST2","Te1/4","1/1/1","10G","fiber","Po20","switch"),("DIST2","Te1/5","1/1/2","10G","fiber","Po20","switch")],
    "CORE2":[("CORE1","Te1/1","Te1/1","40G","stacking","stack","switch"),("DIST1","Te1/2","1/1/3","10G","fiber","Po11","switch"),("DIST1","Te1/3","1/1/4","10G","fiber","Po11","switch"),("DIST2","Te1/4","1/1/3","10G","fiber","Po21","switch"),("DIST2","Te1/5","1/1/4","10G","fiber","Po21","switch")],
    "DIST1":[("EDGE1","1/1/5","1","1G","copper","normal","switch"),("EDGE2","1/1/6","1","1G","copper","normal","switch"),("ACCESS1","1/1/7","1","1G","copper","normal","switch")],
    "DIST2":[("EDGE3","1/1/5","1","1G","copper","normal","switch"),("EDGE4","1/1/6","1","1G","copper","normal","switch"),("ACCESS2","1/1/7","1","1G","copper","normal","switch")],
    "EDGE1":[("EDGE5","2","1","1G","dac","normal","switch"),("AP1","3","eth0","1G","copper","normal","ap")],
    "EDGE2":[("EDGE6","2","1","1G","dac","normal","switch"),("AP2","3","eth0","1G","copper","normal","ap")],
    "EDGE3":[("AP3","3","eth0","1G","copper","normal","ap")],
    "EDGE4":[("AP4","3","eth0","1G","copper","normal","ap")],
    "EDGE5":[],"EDGE6":[],"ACCESS1":[],"ACCESS2":[]
}

for name,vendor,model,ip,stack in switches:
    lines = [f"HOSTNAME: {name}",f"VENDOR: {vendor}",f"MODEL: {model}","DEVICE_TYPE: switch",f"MGMT_IP: {ip}"]
    if name.startswith("CORE"):
        lines.append("ROLE: L3,DHCP")
        lines.append("STP_ROOT: yes")
        lines.append("ROUTE: 0.0.0.0/0 via 10.0.0.254")
        lines.append("DHCP_SCOPE: VLAN10 10.10.10.0/24")
    if stack:
        lines.append(f"STACK_ID: {stack}")
    lines.append("VLAN: 10 Users")
    lines.append("VLAN: 20 Voice")
    for n in neighbors[name]:
        lines.append(f"NEIGHBOR: {','.join(n)}")
    if name=="DIST1":
        lines.append("STP_BLOCKED: 1/1/6")
    (root / f"{name}.txt").write_text("\n".join(lines))

# Add AP and server via excel fallback
ini = """[firewall]
ha=true
nodes=FW-A,FW-B
model=Fortigate-200F
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

wb=Workbook()
ws=wb.active
ws.title="devices"
ws.append(["id","type","model","mgmt_ip"])
ws.append(["SRV1","server","Linux","10.0.10.11"])
ws.append(["SRV2","server","Windows","10.0.10.12"])
ws.append(["AP1","ap","Ubiquiti U6","10.0.20.11"])
ws.append(["AP2","ap","Ubiquiti U6","10.0.20.12"])
ws.append(["AP3","ap","Aruba AP","10.0.20.13"])
ws.append(["AP4","ap","Aruba AP","10.0.20.14"])
ws2=wb.create_sheet("links")
ws2.append(["src","dst","speed","media","type"])
ws2.append(["EDGE5","SRV1","1G","copper","normal"])
ws2.append(["EDGE6","SRV2","1G","copper","normal"])
wb.save(root / "manual_template.xlsx")

with zipfile.ZipFile(root / "switch_exports.zip","w",zipfile.ZIP_DEFLATED) as zf:
    for txt in root.glob("*.txt"):
        zf.write(txt, txt.name)

print("sample data created")
