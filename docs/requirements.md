# Production Parity Requirements

## A. Conflict hygiene and reproducibility
- No merge conflict markers in repository content.
- Python sources parse and import cleanly.
- `requirements.txt` includes dependencies for uploads and PDF conversion.
- Key backend and tooling files remain readable multiline source.

## B. Input and ingest (Option B)
- ZIP input: Cisco/HP ProCurve/Aruba raw-ish command outputs.
- INI edge template: firewall HA, ISP circuits, internet, cloud services, overrides.
- Optional Excel (`devices` + `links`) merged with parsed topology.
- Re-export after filter changes without re-ingest.

## C. Device inclusion and filters
- Include LLDP/CDP neighbors only for switch, firewall, router, server, AP.
- Exclude phones/printers/workstations/etc.
- Frontend exposes: include servers, include access points, include AWS, include Azure, include Other cloud provider.

## D. Diagram rendering
- Server-side SVG and PDF generation.
- Default page 17x11 inches.
- Title block and legend on page 1.
- Straight lines only.
- Trunk links render as double-line only when 2+ members.
- STP root and STP blocked indication only when data exists.
- Stack cluster and firewall HA cluster rendered as shaded boundaries.
- No virtual HA node.
- Core-to-firewall links fan out to both physical HA nodes when enabled (unless disabled in INI).
- Conditional routing/DHCP/VLAN informational boxes:
  - On page 1 if space allows.
  - Otherwise on page 2, even when pagination toggle is disabled.
- Pagination defaults OFF; fit-to-page can override expansion.
- Never clip or overflow exported content.

## E. GUI layout
- Ingest controls top-left.
- Filters top-right.
- Pagination controls beneath filters.
- Export controls at bottom.
- Stale export status visible when filters change.

## F. Parsing structure and runbooks
- Vendor parser modules under `backend/app/vendor_parsers/`.
- Support both one-file multi-command and multi-file per-command ZIP layouts.
- Hostname extraction with filename fallback.
- `command_spec.yaml` and generated runbooks remain aligned.

## G. Sample and verification
- Canonical sample artifacts in `samples/`:
  - `sample_bundle.zip`
  - `sample_edge.ini`
  - `sample_manual.xlsx`
- Sample topology demonstrates: stacks, HA firewalls, ISP/internet/clouds, APs, trunk, STP blocked, and no isolated switches.
- `tools/verify_sample.py` fails loudly with actionable diagnostics for regressions.
