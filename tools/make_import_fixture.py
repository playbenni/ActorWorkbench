"""Blender fixture with arbitrary names and optional actor roles."""
import sys
from pathlib import Path
import bpy

base=Path(__file__).resolve().parent.parent
folder=base/'samples/import-ui-validation'
folder.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(base.parent/'Modfolder/CustomInterceptor.blend'),load_ui=False,use_scripts=False)
for text in list(bpy.data.texts):bpy.data.texts.remove(text)
for collection in bpy.data.collections:collection.name='Source '+collection.name
bpy.data.objects['Collision hull'].name='bunda'
socket=bpy.data.objects['s_main_top_left'];socket.name='mystery_nozzle';del socket['IB_socket']
socket.location.x+=.25
body=bpy.data.objects['Hull']
lod=bpy.data.objects.new('far_away_shape',body.data.copy());bpy.context.scene.collection.objects.link(lod)
for name,position,scale in [('CanopyShell',(0,2,1.1),(.65,1,.18)),('Console',(0,2,1.2),(.5,.25,.15)),('CockpitHitHull',(0,2,1.2),(.6,1,.3)),('unused_bolt',(20,20,20),(.1,.1,.1))]:
    bpy.ops.mesh.primitive_cube_add(size=2,location=position)
    obj=bpy.context.object;obj.name=name;obj.scale=scale
    obj.data.materials.append(bpy.data.materials['Trim - Principled'])
bpy.ops.wm.save_as_mainfile(filepath=str(folder/'arbitrary.blend'),compress=True)
bpy.ops.export_scene.gltf(filepath=str(folder/'arbitrary.glb'),export_format='GLB',export_extras=True)
bpy.ops.export_scene.gltf(filepath=str(folder/'arbitrary.gltf'),export_format='GLTF_SEPARATE',export_extras=True)
print('IMPORT FIXTURES',folder,flush=True)
