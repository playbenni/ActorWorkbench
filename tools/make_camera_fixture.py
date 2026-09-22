"""Blender fixture for a parented camera marker with nontrivial world position."""
import math
from pathlib import Path
import bpy
base=Path(__file__).resolve().parent.parent
bpy.ops.wm.open_mainfile(filepath=str(base/'samples/import-ui-validation/arbitrary.blend'),load_ui=False,use_scripts=False)
parent=bpy.data.objects.new('Camera guide parent',None);bpy.context.scene.collection.objects.link(parent)
parent.location=(4,5,6);parent.rotation_euler.z=math.pi/2;parent.scale=(2,2,2)
eye=bpy.data.objects.new('Pilot eye',None);bpy.context.scene.collection.objects.link(eye)
eye.parent=parent;eye.location=(1,2,3);eye.empty_display_type='ARROWS'
other=bpy.data.objects.new('Alternate pilot eye',None);bpy.context.scene.collection.objects.link(other);other.location=(2,3,4)
bpy.context.view_layer.update()
folder=base/'samples/camera-validation';folder.mkdir(exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(folder/'CameraSource.blend'),compress=True)
print('CAMERA WORLD POSITION',list(eye.matrix_world.translation))
