from pathlib import Path
import yaml

spec = yaml.safe_load(Path('command_spec.yaml').read_text())
outdir = Path('docs/runbooks')
outdir.mkdir(parents=True, exist_ok=True)
for vendor, commands in spec['vendors'].items():
    lines = [f'# {vendor} command runbook', '']
    for idx, cmd in enumerate(commands, start=1):
        lines.append(f'{idx}. `{cmd}`')
    (outdir / f'{vendor}.md').write_text('\n'.join(lines) + '\n')
print('runbooks generated')
