from __future__ import annotations

import io
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.main import app

SAMPLE = ROOT / "sample_data"
OUT = ROOT / "sample_data" / "generated"
OUT.mkdir(exist_ok=True)


def fail(msg: str):
    raise SystemExit(f"VERIFY FAIL: {msg}")


def ensure_sample_inputs() -> None:
    req = [SAMPLE / "switch_exports.zip", SAMPLE / "manual_template.xlsx", SAMPLE / "edge_template.ini"]
    if all(p.exists() for p in req):
        return
    subprocess.run([sys.executable, str(ROOT / "tools" / "create_sample_data.py")], check=True)


def intersects(a, b):
    return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])


def main():
    ensure_sample_inputs()
    client = TestClient(app)
    with open(SAMPLE / "switch_exports.zip", "rb") as zf, open(SAMPLE / "edge_template.ini", "rb") as inf, open(SAMPLE / "manual_template.xlsx", "rb") as exf:
        r = client.post(
            "/api/ingest/bundle",
            files={
                "zip_file": ("switch_exports.zip", zf, "application/zip"),
                "ini_file": ("edge_template.ini", inf, "text/plain"),
                "excel_file": ("manual_template.xlsx", exf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )
    if r.status_code != 200:
        fail(f"ingest failed: {r.status_code}")

    data = {
        "include_servers": "true",
        "include_aps": "true",
        "include_aws": "true",
        "include_azure": "true",
        "include_other_cloud": "true",
        "paginate": "false",
        "fit_to_page": "false",
    }
    svg_resp = client.post("/api/export/svg", data=data)
    pdf_resp = client.post("/api/export/pdf", data=data)
    if svg_resp.status_code != 200 or pdf_resp.status_code != 200:
        fail("export failed")

    svg = svg_resp.text
    (OUT / "verify.svg").write_text(svg)
    (OUT / "verify.pdf").write_bytes(pdf_resp.content)

    root = ET.fromstring(svg)
    ns = {"s": "http://www.w3.org/2000/svg"}

    nodes = root.findall('.//s:rect[@class="node"]', ns)
    if len(nodes) < 12:
        fail("insufficient device nodes")
    edges = root.findall('.//s:line[@class="edge"]', ns) + root.findall('.//s:line[@class="edge trunk"]', ns)
    if len(edges) < 16:
        fail("insufficient edges")

    if not root.findall('.//s:rect[@class="legend"]', ns):
        fail("legend missing")
    if "Routing" not in svg or "DHCP" not in svg or "VLANs" not in svg:
        fail("missing info boxes")

    if "node-Internet" not in svg or "ISP:ISP-A" not in svg or "CLOUD:AWS-Prod" not in svg:
        fail("internet/isp/cloud objects missing")

    trunk_lines = root.findall('.//s:line[@class="edge trunk"]', ns)
    if len(trunk_lines) < 2:
        fail("trunk double lines not detected")

    if "STP blocked" not in svg:
        fail("STP blocked annotation missing")

    clusters = root.findall('.//s:rect[@class="cluster"]', ns)
    if len(clusters) < 2:
        fail("expected stack + HA clusters")

    node_boxes = [(float(n.attrib["x"]), float(n.attrib["y"]), float(n.attrib["width"]), float(n.attrib["height"])) for n in nodes]
    cluster_boxes = [(float(c.attrib["x"]), float(c.attrib["y"]), float(c.attrib["width"]), float(c.attrib["height"])) for c in clusters]

    edge_map = {}
    for e in root.findall('.//s:line', ns):
        if e.attrib.get("class") not in {"edge", "edge trunk"}:
            continue
        edge_id = e.attrib.get("data-edge-id")
        if not edge_id:
            continue
        x1, y1, x2, y2 = map(float, (e.attrib["x1"], e.attrib["y1"], e.attrib["x2"], e.attrib["y2"]))
        edge_map.setdefault(edge_id, []).append((x1, y1, x2, y2))

    labels = root.findall('.//s:text[@class="edge-label"]', ns)
    if not labels:
        fail("no edge labels")

    for label in labels:
        if label.attrib.get("text-anchor") != "middle":
            fail("label text-anchor must be middle")
        txt = label.text or ""
        x = float(label.attrib["x"])
        y = float(label.attrib["y"])
        w = max(42.0, len(txt) * 6.4)
        h = 12.0
        lb = (x - w / 2, y - h + 2, w, h)
        for b in node_boxes + cluster_boxes:
            if intersects(lb, b):
                fail("label overlaps node/cluster")

        edge_id = label.attrib.get("data-edge-id")
        if edge_id not in edge_map:
            fail("label missing edge binding")
        seg = edge_map[edge_id][0]
        mx, my = (seg[0] + seg[2]) / 2, (seg[1] + seg[3]) / 2
        if math.hypot(x - mx, y - my) > 80:
            fail("label too far from link midpoint")

        # vertical label must not overlap other edges
        if abs(seg[0] - seg[2]) < 3:
            for other_id, segs in edge_map.items():
                if other_id == edge_id:
                    continue
                for s in segs:
                    x0, y0 = min(s[0], s[2]) - 1, min(s[1], s[3]) - 1
                    sb = (x0, y0, abs(s[0]-s[2]) + 2, abs(s[1]-s[3]) + 2)
                    if intersects(lb, sb):
                        fail("vertical label overlaps unrelated edge")

    if len(pdf_resp.content) < 1500:
        fail("pdf empty")
    reader = PdfReader(io.BytesIO(pdf_resp.content))
    if len(reader.pages) < 1:
        fail("pdf has no pages")

    print("VERIFY PASS")


if __name__ == "__main__":
    main()
