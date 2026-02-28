from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, Optional

import cairosvg
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .parsers import parse_excel, parse_ini, parse_zip
from .render import Renderer

app = FastAPI(title="Network Diagram Generator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STATE: Dict[str, object] = {"topology": None, "stale": False, "last_svg": None}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/ingest/zip")
async def ingest_zip(zip_file: UploadFile = File(...)) -> dict:
    topo = parse_zip(await zip_file.read())
    STATE["topology"] = topo
    STATE["stale"] = True
    return {"devices": len(topo.devices), "links": len(topo.links), "stale": True}


@app.post("/api/ingest/bundle")
async def ingest_bundle(
    zip_file: UploadFile = File(...),
    ini_file: UploadFile = File(...),
    excel_file: Optional[UploadFile] = File(None),
) -> dict:
    topo = parse_zip(await zip_file.read())
    parse_ini(await ini_file.read(), topo)
    if excel_file:
        parse_excel(await excel_file.read(), topo)
    STATE["topology"] = topo
    STATE["stale"] = True
    return {"devices": len(topo.devices), "links": len(topo.links), "stale": True}


@app.post("/api/export/svg")
async def export_svg(
    include_servers: bool = Form(True),
    include_aps: bool = Form(True),
    include_aws: bool = Form(True),
    include_azure: bool = Form(True),
    include_other_cloud: bool = Form(True),
    paginate: bool = Form(False),
    fit_to_page: bool = Form(False),
):
    if not STATE["topology"]:
        raise HTTPException(status_code=400, detail="No topology loaded")
    renderer = Renderer(
        STATE["topology"],
        {
            "servers": include_servers,
            "aps": include_aps,
            "aws": include_aws,
            "azure": include_azure,
            "other": include_other_cloud,
        },
        paginate,
        fit_to_page,
    )
    svg = renderer.render_svg()
    STATE["stale"] = False
    STATE["last_svg"] = svg
    return Response(content=svg, media_type="image/svg+xml")


@app.post("/api/export/pdf")
async def export_pdf(
    include_servers: bool = Form(True),
    include_aps: bool = Form(True),
    include_aws: bool = Form(True),
    include_azure: bool = Form(True),
    include_other_cloud: bool = Form(True),
    paginate: bool = Form(False),
    fit_to_page: bool = Form(False),
):
    if not STATE["topology"]:
        raise HTTPException(status_code=400, detail="No topology loaded")
    renderer = Renderer(
        STATE["topology"],
        {
            "servers": include_servers,
            "aps": include_aps,
            "aws": include_aws,
            "azure": include_azure,
            "other": include_other_cloud,
        },
        paginate,
        fit_to_page,
    )
    svg = renderer.render_svg()
    pdf = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
    STATE["stale"] = False
    STATE["last_svg"] = svg
    return Response(content=pdf, media_type="application/pdf")


@app.get("/api/status")
def status() -> dict:
    topo = STATE.get("topology")
    return {"loaded": topo is not None, "stale": STATE.get("stale", False)}


frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((frontend_dir / "index.html").read_text())
