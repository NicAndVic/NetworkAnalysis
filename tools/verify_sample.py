from __future__ import annotations

import io
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

def ensure_sample_inputs() -> None:
    if (SAMPLE / "switch_exports.zip").exists() and (SAMPLE / "manual_template.xlsx").exists() and (SAMPLE / "edge_template.ini").exists():
        return
    subprocess.run([sys.executable, str(ROOT / "tools" / "create_sample_data.py")], check=True)



def rects_from_svg(svg_text: str, klass: str):
    root = ET.fromstring(svg_text)
    ns = {"s": "http://www.w3.org/2000/svg"}
    out = []
    for r in root.findall(".//s:rect", ns):
        if r.attrib.get("class") == klass:
            out.append((float(r.attrib["x"]), float(r.attrib["y"]), float(r.attrib["width"]), float(r.attrib["height"])))
    return out


def label_boxes(svg_text: str):
    root = ET.fromstring(svg_text)
    ns = {"s": "http://www.w3.org/2000/svg"}
    boxes = []
    for t in root.findall('.//s:text', ns):
        if t.attrib.get("class") != "edge-label":
            continue
        txt = (t.text or "")
        x = float(t.attrib["x"])
        y = float(t.attrib["y"])
        w = max(45.0, len(txt) * 6.0)
        h = 12.0
        boxes.append((x, y - h, w, h))
    return boxes


def intersects(a, b):
    return not (a[0] + a[2] < b[0] or b[0] + b[2] < a[0] or a[1] + a[3] < b[1] or b[1] + b[3] < a[1])


def fail(msg: str):
    raise SystemExit(f"VERIFY FAIL: {msg}")


def main():
    ensure_sample_inputs()
    client = TestClient(app)
    with open(SAMPLE / "switch_exports.zip", "rb") as zf, open(SAMPLE / "edge_template.ini", "rb") as inf, open(SAMPLE / "manual_template.xlsx", "rb") as exf:
        resp = client.post(
            "/api/ingest/bundle",
            files={"zip_file": ("switch_exports.zip", zf, "application/zip"), "ini_file": ("edge_template.ini", inf, "text/plain"), "excel_file": ("manual_template.xlsx", exf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    if resp.status_code != 200:
        fail("ingest failed")

    data = {"include_servers": "true", "include_aps": "true", "include_aws": "true", "include_azure": "true", "include_other_cloud": "true", "paginate": "false", "fit_to_page": "false"}
    svg_resp = client.post('/api/export/svg', data=data)
    pdf_resp = client.post('/api/export/pdf', data=data)
    if svg_resp.status_code != 200 or pdf_resp.status_code != 200:
        fail("export failed")

    svg = svg_resp.text
    (OUT / "verify.svg").write_text(svg)
    (OUT / "verify.pdf").write_bytes(pdf_resp.content)

    if svg.count('class="node"') < 10 or svg.count('class="edge"') < 10:
        fail("missing nodes/edges")
    if "Legend" not in svg:
        fail("legend missing")
    for name in ["Routing", "DHCP", "VLANs"]:
        if name not in svg:
            fail(f"{name} box missing")

    nodes = rects_from_svg(svg, "node")
    clusters = rects_from_svg(svg, "cluster")
    for lb in label_boxes(svg):
        for b in nodes + clusters:
            if intersects(lb, b):
                fail("label overlaps node/cluster")

    if len(pdf_resp.content) < 1000:
        fail("pdf empty")
    reader = PdfReader(io.BytesIO(pdf_resp.content))
    if len(reader.pages) < 1:
        fail("pdf has no pages")
    box = reader.pages[0].mediabox
    width = float(box.width)
    height = float(box.height)
    if not ((abs(width - 1224) <= 2 and abs(height - 792) <= 2) or (width >= 1224 and height >= 560)):
        fail(f"pdf page size/scaling unexpected: {width}x{height}")

    print("VERIFY PASS")


if __name__ == "__main__":
    main()
