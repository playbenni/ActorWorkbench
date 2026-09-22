"""Install a staged mod into TEMPORARY COPIES and verify restoration, never the game."""
import sys,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ibworkbench.formats import inside,Mesh,digest,xml_read
from ibworkbench.mods import atomic_write,install,restore

game=Path(sys.argv[1]).resolve()
mod=Path(sys.argv[2]).resolve()
manifest=json.loads((mod/'mod.json').read_text('utf8'))
with tempfile.TemporaryDirectory(prefix='ibaw-copy-test-') as folder:
    root=Path(folder)
    for item in manifest['files']:
        data=inside(game,item['path']).read_bytes()
        atomic_write(inside(root/'game-copy',item['path']),data)
    backup=install(mod,root/'game-copy',root/'backups')
    for item in manifest['files']:
        path=inside(root/'game-copy',item['path'])
        assert digest(path.read_bytes())==item['after']
        if path.suffix=='.insm': Mesh(path.read_bytes())
        elif path.suffix=='.xml': xml_read(path)
    restore(backup,root/'game-copy')
    for item in manifest['files']:
        assert digest(inside(root/'game-copy',item['path']).read_bytes())==item['before']
print('STAGED MOD COPY TEST PASSED',len(manifest['files']),'files; game installation was read-only')
