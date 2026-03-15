from __future__ import annotations

import io
import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app

BUNDLE = ROOT / "samples" / "sample_bundle.zip"
INI = ROOT / "samples" / "sample_edge.ini"
EXCEL = ROOT / "samples" / "sample_manual.xlsx"
OUT_DIR = ROOT / "samples" / "generated"
SVG_OUT = OUT_DIR / "verify.svg"
PDF_OUT = OUT_DIR / "verify.pdf"

SVG_NS = "{http://www.w3.org/2000/svg}"


class VerifyError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise VerifyError(message)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def ensure_artifacts() -> None:
    missing = [path for path in (BUNDLE, INI, EXCEL) if not path.exists()]
    if missing:
        fail(f"Missing sample artifacts: {', '.join(str(path) for path in missing)}")




def verify_repo_hygiene() -> None:
    bidi_cmd = [sys.executable, str(ROOT / "tools" / "check_bidi.py")]
    bidi = subprocess.run(bidi_cmd, capture_output=True, text=True)
    assert_true(bidi.returncode == 0, f"Bidi scan failed: {bidi.stdout}{bidi.stderr}")

    tracked_generated = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    bad = [path for path in tracked_generated if path.startswith("samples/generated/")]
    assert_true(not bad, f"Generated artifacts must not be tracked: {', '.join(bad)}")

def ingest_and_export() -> tuple[str, bytes]:
    client = TestClient(app)
    with BUNDLE.open("rb") as bundle_file, INI.open("rb") as ini_file, EXCEL.open("rb") as excel_file:
        response = client.post(
            "/api/ingest/bundle",
            files={
                "zip_file": (BUNDLE.name, bundle_file, "application/zip"),
                "ini_file": (INI.name, ini_file, "text/plain"),
                "excel_file": (EXCEL.name, excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )
    assert_true(response.status_code == 200, f"ingest failed: {response.status_code} {response.text}")

    form = {
        "include_servers": "true",
        "include_aps": "true",
        "include_aws": "true",
        "include_azure": "true",
        "include_other_cloud": "true",
        "paginate": "false",
        "fit_to_page": "false",
    }

    svg_response = client.post("/api/export/svg", data=form)
    assert_true(svg_response.status_code == 200, f"svg export failed: {svg_response.status_code} {svg_response.text}")

    pdf_response = client.post("/api/export/pdf", data=form)
    assert_true(pdf_response.status_code == 200, f"pdf export failed: {pdf_response.status_code} {pdf_response.text}")
    return svg_response.text, pdf_response.content


def _parse_points(polyline_points: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for token in polyline_points.strip().split():
        x_str, y_str = token.split(",")
        points.append((float(x_str), float(y_str)))
    return points


def _box_from_rect(el: ET.Element) -> tuple[float, float, float, float]:
    x = float(el.attrib.get("x", "0"))
    y = float(el.attrib.get("y", "0"))
    w = float(el.attrib.get("width", "0"))
    h = float(el.attrib.get("height", "0"))
    return x, y, x + w, y + h


def _seg_intersects_box(p1: tuple[float, float], p2: tuple[float, float], box: tuple[float, float, float, float]) -> bool:
    bx0, by0, bx1, by1 = box
    x1, y1 = p1
    x2, y2 = p2
    if abs(x1 - x2) < 1e-6:
        x = x1
        if not (bx0 < x < bx1):
            return False
        low, high = sorted([y1, y2])
        return low < by1 and high > by0
    if abs(y1 - y2) < 1e-6:
        y = y1
        if not (by0 < y < by1):
            return False
        low, high = sorted([x1, x2])
        return low < bx1 and high > bx0
    return False


def _box_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def verify_svg(svg: str) -> None:
    assert_true("<svg" in svg, "SVG root missing")
    assert_true("<rect class=\"edge-label-bg\"" not in svg, "Label background rectangles are forbidden")

    root = ET.fromstring(svg)
    rects = root.findall(f".//{SVG_NS}rect")
    polylines = root.findall(f".//{SVG_NS}polyline")
    texts = root.findall(f".//{SVG_NS}text")

    node_rects = [r for r in rects if "node" in r.attrib.get("class", "")]
    cluster_rects = [r for r in rects if "cluster" in r.attrib.get("class", "")]
    assert_true(len(node_rects) >= 18, "Expected at least 18 node rectangles")
    assert_true(len(polylines) >= 18, "Expected at least 18 routed edge polylines")
    assert_true(any("legend" in r.attrib.get("class", "") for r in rects), "Legend missing")
    assert_true(any("title-block" in r.attrib.get("class", "") for r in rects), "Title block missing")
    assert_true(any("cluster stack" in r.attrib.get("class", "") for r in rects), "Stack cluster shading missing")
    assert_true(any("cluster ha" in r.attrib.get("class", "") for r in rects), "HA cluster shading missing")

    for keyword in ["Internet", "PrimaryISP", "BackupISP", "AWS-Prod", "Azure-DR", "Other-SaaS"]:
        assert_true(keyword in svg, f"Expected object missing from SVG: {keyword}")

    node_boxes = [_box_from_rect(r) for r in node_rects]
    cluster_boxes = [_box_from_rect(r) for r in cluster_rects]
    blockers = [("node", b) for b in node_boxes] + [("cluster", b) for b in cluster_boxes]

    # Link/segment collision checks
    for pl in polylines:
        pts = _parse_points(pl.attrib.get("points", ""))
        edge_id = pl.attrib.get("data-edge-id", "?")
        src = pl.attrib.get("data-src", "")
        dst = pl.attrib.get("data-dst", "")

        # orthogonal only
        for p1, p2 in zip(pts, pts[1:]):
            assert_true(abs(p1[0] - p2[0]) < 1e-6 or abs(p1[1] - p2[1]) < 1e-6, f"Edge {edge_id} contains non-orthogonal segment")

        # avoid blocker intersections except endpoint touching
        for p1, p2 in zip(pts, pts[1:]):
            for btype, box in blockers:
                if _seg_intersects_box(p1, p2, box):
                    # allow first/last stubs to leave or enter endpoint zones
                    if (p1 == pts[0] and p2 == pts[1]) or (p1 == pts[-2] and p2 == pts[-1]):
                        continue
                    # cluster boxes may contain endpoint zones; permit intersections when segment endpoint is inside cluster
                    if btype == "cluster":
                        if (box[0] < p1[0] < box[2] and box[1] < p1[1] < box[3]) or (box[0] < p2[0] < box[2] and box[1] < p2[1] < box[3]):
                            continue
                    fail(f"Edge {edge_id} intersects node/cluster box (src={src}, dst={dst})")

    # trunk validation
    trunk_groups: dict[str, int] = {}
    for pl in polylines:
        if "trunk" in pl.attrib.get("class", ""):
            eid = pl.attrib.get("data-edge-id", "")
            trunk_groups[eid] = trunk_groups.get(eid, 0) + 1
    assert_true(trunk_groups, "Expected at least one trunk edge")
    for eid, count in trunk_groups.items():
        assert_true(count == 2, f"Trunk {eid} must render exactly as two parallel polylines")

    assert_true("members=" in svg and "Po1" in svg, "Trunk label missing trunk id/member count")
    assert_true("STP blocked" in svg, "STP blocked annotation missing")

    # stack links direct (single segment)
    stack_edges = [pl for pl in polylines if pl.attrib.get("data-media") == "stacking"]
    assert_true(stack_edges, "Expected stacking links")
    for pl in stack_edges:
        pts = _parse_points(pl.attrib.get("points", ""))
        assert_true(len(pts) == 2, f"Stacking edge {pl.attrib.get('data-edge-id')} must be direct and not routed through channels")

    # label checks
    edge_segments: dict[str, list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    edge_media: dict[str, str] = {}
    for pl in polylines:
        eid = pl.attrib.get("data-edge-id", "")
        pts = _parse_points(pl.attrib.get("points", ""))
        edge_segments.setdefault(eid, []).extend(list(zip(pts, pts[1:])))
        edge_media[eid] = pl.attrib.get("data-media", "")

    label_texts = [t for t in texts if "edge-label" in t.attrib.get("class", "")]
    assert_true(label_texts, "Missing edge labels")
    label_bboxes: list[tuple[float, float, float, float, str]] = []
    for label in label_texts:
        assert_true(label.attrib.get("text-anchor") == "middle", "Edge labels must use midpoint anchoring")
        txt = "".join(label.itertext())
        x = float(label.attrib.get("x", "0"))
        y = float(label.attrib.get("y", "0"))
        width = max(40.0, len(txt) * 6.2)
        bbox = (x - width / 2, y - 10, x + width / 2, y + 2)

        for _, box in blockers:
            assert_true(not _box_intersects(bbox, box), f"Label overlaps node/cluster: {txt}")

        for ob in label_bboxes:
            assert_true(not _box_intersects(bbox, ob[:4]), f"Label-label overlap detected: {txt} overlaps {ob[4]}")
        label_bboxes.append((*bbox, txt))

        seg = label.attrib.get("data-seg", "")
        assert_true(seg, f"Label {txt} missing data-seg metadata")
        sx1, sy1, sx2, sy2 = [float(v) for v in seg.split(",")]
        if abs(sx1 - sx2) < 1e-6:
            dist = abs(x - sx1)
        else:
            dist = abs(y - sy1)
        eid = label.attrib.get("data-edge-id", "")
        max_dist = 24 if edge_media.get(eid) != "stacking" else 80
        assert_true(dist <= max_dist, f"Label too far from chosen segment ({dist:.1f}px): {txt}")

        # vertical label overlap rules
        if abs(sx1 - sx2) < 1e-6:
            for other_id, segs in edge_segments.items():
                if other_id == eid:
                    continue
                for p1, p2 in segs:
                    if _seg_intersects_box(p1, p2, bbox):
                        fail(f"Vertical label overlaps foreign edge: {txt}")

    assert_true("Routing table" in svg and "DHCP scopes" in svg and "VLANs" in svg, "Informational boxes missing")


def verify_pdf(pdf_bytes: bytes) -> None:
    assert_true(len(pdf_bytes) > 2000, "PDF output is unexpectedly small")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert_true(len(reader.pages) >= 1, "PDF must contain at least one page")
    page = reader.pages[0]
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    assert_true(width >= 1224 and height >= 700, f"PDF page dimensions unexpectedly small: {width}x{height}")


def main() -> None:
    verify_repo_hygiene()
    ensure_artifacts()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg, pdf = ingest_and_export()
    SVG_OUT.write_text(svg)
    PDF_OUT.write_bytes(pdf)
    verify_svg(svg)
    verify_pdf(pdf)
    print("[verify] PASS: sample ingest/export parity checks completed")


if __name__ == "__main__":
    try:
        main()
    except VerifyError as exc:
        raise SystemExit(f"[verify] FAIL: {exc}")
