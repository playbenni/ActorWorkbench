"""Staged, hash-checked installation and restoration. Never patch originals in place."""
from pathlib import Path
import datetime
import json
import os
import tempfile
from .formats import inside, digest


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.ibaw-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validated_entries(folder, root, restore=False):
    folder, root = Path(folder).resolve(), Path(root).resolve()
    manifest = json.loads((folder/'mod.json').read_text('utf8'))
    if manifest.get('version') not in (1,2):
        raise ValueError('Unsupported mod manifest')
    for dependency in manifest.get('requires',[]):
        if digest(inside(root,dependency['path']).read_bytes()) != dependency['sha256']:
            raise ValueError('Game dependency differs: '+dependency['path'])
    seen, items = set(), []
    for entry in manifest['files']:
        ref = entry['path']
        if ref.lower() in seen or ref.split('/')[0] not in ('Dev','Engine') or Path(ref).suffix.lower() not in ('.insm','.cmti','.xml','.txb'):
            raise ValueError('Unsupported/duplicate mod target: '+ref)
        seen.add(ref.lower())
        target = inside(root, ref)
        payload = inside(folder/'payload', ref)
        if entry['before'] is None and manifest['version'] != 2:
            raise ValueError('New files require mod manifest version 2')
        current = target.read_bytes() if target.exists() else None
        replacement = None if restore and entry['before'] is None else payload.read_bytes()
        expected = entry['after'] if restore else entry['before']
        replacement_hash = entry['before'] if restore else entry['after']
        if (digest(current) if current is not None else None) != expected or (digest(replacement) if replacement is not None else None) != replacement_hash:
            raise ValueError('Checksum conflict; no files changed: '+ref)
        items.append((ref, target, current, replacement))
    if not items:
        raise ValueError('No changed files in this mod')
    return manifest, items


def install(folder, game, backup_parent):
    manifest, items = validated_entries(folder, game)
    backup_parent = Path(backup_parent).resolve()
    backup_parent.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-'), dir=backup_parent))
    # All originals and recovery manifest are durable before any game write.
    for ref, _, original, _ in items:
        if original is not None:
            atomic_write(inside(backup/'payload', ref), original)
    atomic_write(backup/'mod.json', json.dumps(manifest, indent=2).encode())
    atomic_write(backup/'state.json', b'{"state":"prepared"}')
    changed = []
    try:
        for ref, target, original, replacement in items:
            if (target.read_bytes() if target.exists() else None) != original:
                raise ValueError('File changed during installation: '+ref)
            atomic_write(target, replacement)
            changed.append((target, original))
        atomic_write(backup/'state.json', b'{"state":"installed"}')
    except Exception:
        for target, original in reversed(changed):
            if original is None:
                target.unlink()
            else:
                atomic_write(target, original)
        atomic_write(backup/'state.json', b'{"state":"rolled_back"}')
        raise
    return backup


def restore(backup, game):
    _, items = validated_entries(backup, game, restore=True)
    changed = []
    try:
        for ref, target, current, original in items:
            if target.read_bytes() != current:
                raise ValueError('File changed during restore: '+ref)
            if original is None:
                target.unlink()
            else:
                atomic_write(target, original)
            changed.append((target, current))
    except Exception:
        for target, current in reversed(changed):
            atomic_write(target, current)
        raise
    atomic_write(Path(backup)/'state.json', b'{"state":"restored"}')
