"""Copy installed dependency notices alongside the packaged application."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
output = root / 'dist/ActorWorkbench/ThirdPartyLicenses'
output.mkdir(parents=True, exist_ok=True)
shutil.copy2(Path(sys.base_prefix) / 'LICENSE.txt', output / 'Python-LICENSE.txt')
for name in ('numpy', 'pillow', 'cryptography', 'cffi', 'pyinstaller'):
    package = distribution(name)
    found = False
    for entry in package.files or ():
        if any(part.lower().startswith(('license', 'copying', 'notice')) for part in entry.parts):
            source = Path(package.locate_file(entry))
            if source.is_file():
                destination = output / name / Path(*entry.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                found = True
    if not found:
        raise RuntimeError(f'Missing distribution license: {name}')
for source in (root / 'build/tcl-runtime').rglob('license.terms'):
    destination = output / 'TclTk' / source.relative_to(root / 'build/tcl-runtime')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
print(f'Collected runtime license notices in {output}')
