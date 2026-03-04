# Network Diagram Generator

Single-service FastAPI application that serves both frontend and API. It ingests Option B inputs (ZIP switch exports + INI edge template + optional Excel), then renders deterministic server-side SVG/PDF diagrams.

## Documentation
- Requirements and parity guardrails: `docs/requirements.md`
- Pipeline architecture: `docs/architecture.md`
- Vendor command runbooks: `docs/runbooks/cisco.md`, `docs/runbooks/hp_procurve.md`, `docs/runbooks/aruba.md`

## Features
- `POST /api/ingest/bundle` for ZIP + INI + optional Excel.
- `POST /api/export/svg` and `POST /api/export/pdf` with filter controls and pagination controls.
- Frontend includes stale export indicator and supports re-export without re-ingest.
- Renderer includes title block, legend, stack/HA shaded clusters, trunk double-lines, STP blocked markings, and conditional informational boxes.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
```

## Sample data
Generate canonical artifacts:
```bash
python tools/create_sample_data.py
```
Generated files:
- `samples/sample_bundle.zip`
- `samples/sample_edge.ini`
- `samples/sample_manual.xlsx`

## Verification
```bash
python tools/verify_sample.py
```

## Runbook regeneration
```bash
python generate_runbooks.py
```
