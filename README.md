# Network Diagram Generator

Single-service FastAPI + React application that ingests switch exports (ZIP), edge template INI, and optional Excel fallback data, then renders deterministic server-side SVG/PDF diagrams.

## Features
- Ingest endpoints:
  - `POST /api/ingest/zip`
  - `POST /api/ingest/bundle` (zip + ini + optional excel)
- Export endpoints:
  - `POST /api/export/svg`
  - `POST /api/export/pdf`
- Browser GUI for ingest, filters, pagination options, stale export indicator, and re-export without re-ingest.
- Parsers focused on Cisco, HP ProCurve, Aruba raw command exports (LLDP/CDP, running-config, spanning-tree, VLAN, route, DHCP).
- Topology merge from ZIP + INI + Excel.
- Diagram includes title block, legend, cluster shading (stack/HA), trunks (double-lines), STP blocked notation, VLAN/DHCP/route info boxes.
- Verification harness checks ingest/export quality and SVG geometry constraints.

## Repository layout
- `backend/app/main.py`: FastAPI service + API routes + frontend hosting.
- `backend/app/parsers.py`: ZIP/INI/Excel parsing + topology merge.
- `backend/app/render.py`: layout + SVG rendering + link label collision avoidance.
- `frontend/index.html`: React GUI.
- `sample_data/`: sample bundle and source command txt files.
- `tools/verify_sample.py`: automated regression verifier.
- `command_spec.yaml` + `generate_runbooks.py`: command catalog and runbook generation.
- `docs/runbooks/`: generated runbooks.

## Requirements
- Python 3.10+
- Linux or Windows

## Install
```bash
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run locally
```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
```
Open `http://localhost:8080`.

## Use sample bundle
Files in `sample_data/` include command-output `.txt` sources and `edge_template.ini`.
Generate sample ZIP/XLSX bundle with:
```bash
python tools/create_sample_data.py
```
Then upload generated files (`switch_exports.zip`, `edge_template.ini`, `manual_template.xlsx`) in GUI.

## Run verification harness
```bash
python tools/verify_sample.py
```
Verifier checks:
- ingest and both exports succeed
- SVG has nodes/edges, cloud/ISP/internet objects, stack+HA clusters
- legend on page 1 and routing/DHCP/VLAN boxes present
- trunk double-line and STP blocked annotation are present
- labels use midpoint anchoring and avoid node/cluster collisions
- PDF is non-empty

## Regenerate runbooks
```bash
python generate_runbooks.py
```

## Linux systemd deployment example (Ubuntu)
Create `/etc/systemd/system/network-diagram.service`:
```ini
[Unit]
Description=Network Diagram Generator
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/NetworkAnalysis
Environment="PATH=/opt/NetworkAnalysis/.venv/bin"
ExecStart=/opt/NetworkAnalysis/.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable/start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable network-diagram.service
sudo systemctl start network-diagram.service
sudo systemctl status network-diagram.service
```

## Windows run example
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
```

## Future roadmap placeholders
- Multi-site support with VPN tunnel visualization modes.
- Project save/load for iterative updates.
- Active discovery from IP ranges with credential prompts.
