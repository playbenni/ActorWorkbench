"""Headless integration inspection, optional test edit, and preview render."""
import sys,json,math
from pathlib import Path
import bpy
from mathutils import Vector

path = Path(sys.argv[sys.argv.index('--')+1]).resolve()
bpy.ops.wm.open_mainfile(filepath=str(path),use_scripts=False)
manifest = json.loads(bpy.data.texts['IB_ACTOR_MANIFEST.json'].as_string())
meshes = [o for o in bpy.context.scene.objects if o.type=='MESH']
print('VERIFIED',json.dumps(dict(nodes=len(manifest['nodes']),meshes=len(meshes),counts=manifest['counts'],
     materials=len(manifest['materials']),packed_textures=sum(bool(i.packed_file) for i in bpy.data.images),
     triangles=sum(len(o.data.polygons) for o in meshes))))
assert meshes and all(len(o.data.polygons)>0 for o in meshes)
assert len([o for o in bpy.context.scene.objects if 'IB_id' in o])==len(manifest['nodes'])
if '--bad-topology' in sys.argv:
    target=next(o for o in meshes if o.users_collection[0].name=='Render')
    target.data.loops[0].vertex_index=target.data.loops[1].vertex_index
    bpy.ops.wm.save_as_mainfile(filepath=str(path.with_name(path.stem+'-bad-topology.blend')),compress=True)
if '--edit' in sys.argv:
    target=next(o for o in meshes if o.users_collection[0].name=='Render')
    target.data.vertices[0].co.z += .1
    light=next((o for o in bpy.context.scene.objects if o.type=='LIGHT'),None)
    if light:
        light.data.energy *= 1.1
    edited=path.with_name(path.stem+'-edited.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(edited),compress=True)
if '--render' in sys.argv:
    if '--test-unflip-uv' in sys.argv:
        for mesh in {o.data for o in meshes}:
            for layer in mesh.uv_layers:
                for uv in layer.data:
                    uv.uv.y = 1-uv.uv.y
    scene=bpy.context.scene
    bpy.context.view_layer.update()
    visible=[o for o in meshes if not o.hide_get()]
    coords=[o.matrix_world@Vector(v) for o in visible for v in o.bound_box]
    lo=Vector(tuple(min(v[i] for v in coords) for i in range(3)))
    hi=Vector(tuple(max(v[i] for v in coords) for i in range(3)))
    center=(lo+hi)/2
    radius=max((hi-lo).length/2,1)
    camera=bpy.data.objects.new('Preview camera',bpy.data.cameras.new('Preview camera'))
    scene.collection.objects.link(camera)
    camera.location=center+Vector((1,-1.4,1.2)).normalized()*radius*3.5
    camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.clip_end=radius*20
    camera.data.clip_start=radius/10000
    scene.camera=camera
    for index, direction in enumerate(((1,-1,2),(-1,1,1))):
        lamp=bpy.data.objects.new('Preview sun',bpy.data.lights.new('Preview sun','SUN'))
        scene.collection.objects.link(lamp)
        lamp.rotation_euler=Vector(direction).to_track_quat('Z','Y').to_euler()
        lamp.data.energy=2 if index==0 else .8
        lamp.data.angle=.3
    scene.render.engine='CYCLES'
    scene.cycles.samples=16
    scene.cycles.use_denoising=True
    scene.render.resolution_x=1000
    scene.render.resolution_y=750
    scene.render.resolution_percentage=100
    scene.render.filepath=str(path.with_name(path.stem+'-unflipped.png') if '--test-unflip-uv' in sys.argv else path.with_suffix('.png'))
    bpy.ops.render.render(write_still=True)
