"""Headless Blender integration: no game writes, stage then test on temporary copies."""
import sys
import json
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy
import numpy as np
from mathutils import Vector
from ibworkbench.blender_worker import build_mod
from ibworkbench.formats import Mesh, digest, texture_png
from ibworkbench.mods import install, restore, atomic_write

blend, output, game = map(Path, sys.argv[sys.argv.index('--')+1:][:3])
output.mkdir(parents=True, exist_ok=False)
build_mod(dict(blend=str(blend),game=str(game),output=str(output/'unchanged')))
assert json.loads((output/'unchanged/mod.json').read_text())['files'] == [], 'Unchanged export must stage no changes'
bpy.ops.wm.open_mainfile(filepath=str(blend),use_scripts=False)
project = json.loads(bpy.data.texts['IB_ACTOR_MANIFEST.json'].as_string())
objects = {o['IB_id']:o for o in bpy.context.scene.objects if 'IB_id' in o}
render = next(objects[n['id']] for n in project['nodes'] if n.get('role')=='Render')
bpy.context.view_layer.update()
corners = [render.matrix_world @ Vector(c) for c in render.bound_box]
low = Vector(tuple(min(c[a] for c in corners) for a in range(3)))
high = Vector(tuple(max(c[a] for c in corners) for a in range(3)))
for item in project['nodes']:
    if item.get('role') not in ('Render','LOD','Collision'):
        continue
    original = objects[item['id']]
    bpy.ops.mesh.primitive_cube_add(size=2, location=(low+high)/2)
    replacement = bpy.context.object
    replacement.name = 'REPLACE:'+original.name
    replacement.scale = (high-low)*.6
    # No materials means original slot zero. The exporter fills missing UV1/2
    # from the cube's UV0 and computes per-corner normal/tangent frames.
material = render.data.materials[0]
params = project['materials'][material['IB_material']]['params']
node = next(n for n in material.node_tree.nodes if n.type=='TEX_IMAGE' and n.name in params and params[n.name].get('texture') in project['textures'])
texture_key = params[node.name]['texture']
image = bpy.data.images.new('Replacement test paint',16,16,alpha=True)
image.colorspace_settings.name = node.image.colorspace_settings.name
image.pixels[:] = [.2,.4,.6,1]*256
image.pack()
node.image = image
edited = output/'replacement.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(edited),compress=True)
build_mod(dict(blend=str(edited),game=str(game),output=str(output/'mod')))
mod = json.loads((output/'mod/mod.json').read_text())
assert any(f['path'].endswith('.txb') for f in mod['files'])
assert any(f['path']==project['actor'] for f in mod['files']), 'Larger geometry must expand WorldBoxSize'
assert not any('are unchanged' in warning for warning in mod['warnings'])
for entry in mod['files']:
    payload = (output/'mod/payload'/entry['path']).read_bytes()
    if entry['path'].endswith('.insm'):
        old, new = Mesh((game/entry['path']).read_bytes()), Mesh(payload)
        assert new.ni == 36 and new.nv in (8,24), (entry['path'],new.nv,new.ni)
        assert [g['material'] for g in old.groups] == [g['material'] for g in new.groups]
        assert [s['name'] for s in old.sockets] == [s['name'] for s in new.sockets]
        if new.attribute(3) is not None:
            normals = new.attribute(3)[:, :3]
            triangles = new.positions[new.faces]
            cross = -np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
            assert (np.sum(cross*normals[new.faces[:,0]],axis=1)>0).all(), 'Incorrect winding/normals'
    assert digest((game/entry['path']).read_bytes()) == entry['before']
with tempfile.TemporaryDirectory(prefix='ibaw-install-test-') as folder:
    fake = Path(folder)/'game'
    for entry in mod['files']:
        atomic_write(fake/entry['path'],(game/entry['path']).read_bytes())
    backup = install(output/'mod',fake,Path(folder)/'backups')
    for entry in mod['files']:
        assert digest((fake/entry['path']).read_bytes()) == entry['after']
    restore(backup,fake)
    for entry in mod['files']:
        assert digest((fake/entry['path']).read_bytes()) == entry['before']
print('FULL REPLACEMENT PASSED:',len(mod['files']),'files; game originals untouched',flush=True)
