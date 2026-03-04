from __future__ import annotations

import io
import re
import sys
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


def fail(message: str) -> None:
    raise SystemExit(f"[verify] FAIL: {message}")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def ensure_artifacts() -> None:
    missing = [path for path in (BUNDLE, INI, EXCEL) if not path.exists()]
    if missing:
        fail(f"Missing sample artifacts: {', '.join(str(path) for path in missing)}")


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


def verify_svg(svg: str) -> None:
    assert_true("<svg" in svg, "SVG root missing")
    assert_true(svg.count('class="node') >= 18, "Expected at least 18 node rectangles in SVG")
    assert_true(svg.count('class="edge') >= 18, "Expected at least 18 edges in SVG")

    assert_true('class="legend"' in svg, "Legend missing")
    assert_true('class="title-block"' in svg, "Title block missing")

    assert_true('class="cluster stack"' in svg, "Stack cluster shading missing")
    assert_true('class="cluster ha"' in svg, "HA cluster shading missing")

    for keyword in ["Internet", "PrimaryISP", "BackupISP", "AWS-Prod", "Azure-DR", "Other-SaaS"]:
        assert_true(keyword in svg, f"Expected cloud/isp/internet object missing: {keyword}")

    trunk_lines = len(re.findall(r'class="edge trunk"', svg))
    assert_true(trunk_lines >= 2, "Expected trunk to render as double-line")
    assert_true("members=" in svg and "Po1" in svg, "Trunk label missing trunk id/member count")

    assert_true("STP blocked" in svg, "STP blocked example missing")
    assert_true('text-anchor="middle"' in svg, "Edge labels must be midpoint anchored")
    assert_true("<rect class=\"info-box\"" in svg, "Expected informational boxes for routing/DHCP/VLAN")
    assert_true("Routing table" in svg and "DHCP scopes" in svg and "VLANs" in svg, "Missing one or more info box titles")
    assert_true("<rect class=\"edge-label-bg\"" not in svg, "Label background rectangles must not be used")


def verify_pdf(pdf_bytes: bytes) -> None:
    assert_true(len(pdf_bytes) > 2000, "PDF output is unexpectedly small")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert_true(len(reader.pages) >= 1, "PDF must contain at least one page")
    page = reader.pages[0]
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    assert_true(width >= 1224 and height >= 742, f"PDF page dimensions unexpectedly small for 17x11 parity mode: {width}x{height}")


def main() -> None:
    ensure_artifacts()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg, pdf = ingest_and_export()
    SVG_OUT.write_text(svg)
    PDF_OUT.write_bytes(pdf)
    verify_svg(svg)
    verify_pdf(pdf)
    print("[verify] PASS: sample ingest/export parity checks completed")


if __name__ == "__main__":
    main()
