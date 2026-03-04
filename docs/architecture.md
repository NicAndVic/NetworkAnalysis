# Architecture

## Overview
The service runs as one FastAPI process that serves both API routes and the frontend (`frontend/index.html`).

## Pipeline
1. **Ingest**
   - ZIP parser reads switch exports and routes each file through vendor-specific parsing.
   - INI parser adds firewall/ISP/cloud overlays and redundancy rules.
   - Excel parser merges optional manual `devices` and `links` rows.
2. **Parse and normalize**
   - Vendor modules normalize interfaces, speeds, and neighbor records.
   - Inclusion rules keep only switch/firewall/router/server/AP neighbor types.
   - LACP/Port-channel members are collapsed into trunk links only when >=2 members.
3. **Topology assembly**
   - Parsed devices and links become a `Topology` object.
   - Route/DHCP/VLAN informational lines are deduplicated for rendering.
4. **Deterministic layout**
   - Renderer assigns device layers (cloud→internet→isp→firewall→switch→endpoint).
   - Stack and HA clusters are boxed with shaded boundaries.
   - Links are straight-line segments with deterministic label placement.
5. **Export**
   - SVG is generated server-side.
   - PDF is generated from SVG via CairoSVG.
   - Frontend supports re-export with changed filters without re-ingest.

## Main modules
- `backend/app/main.py`: API, static frontend hosting, and in-memory topology state.
- `backend/app/parsers.py`: ZIP/INI/Excel orchestration and topology merge.
- `backend/app/vendor_parsers/*.py`: vendor command extraction logic.
- `backend/app/render.py`: layout + SVG generation.
- `tools/create_sample_data.py`: canonical sample artifact generation.
- `tools/verify_sample.py`: regression verification harness.
