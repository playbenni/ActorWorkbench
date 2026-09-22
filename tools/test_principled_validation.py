"""Run with Blender --background --python-exit-code 1 --python this_file."""
import sys
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ibworkbench.blender_new_actor import validate_principled

mat=bpy.data.materials.new('Validation material');mat.use_nodes=True
bsdf,output=validate_principled(mat)
for key,value in [('Transmission Weight',.5),('Alpha',.5),('Coat Weight',.2),('IOR',1.9)]:
    old=bsdf.inputs[key].default_value;bsdf.inputs[key].default_value=value
    try:validate_principled(mat)
    except ValueError as error:assert key in str(error)
    else:raise AssertionError('Unsupported input accepted: '+key)
    bsdf.inputs[key].default_value=old
texture=mat.node_tree.nodes.new('ShaderNodeTexImage')
mat.node_tree.links.new(texture.outputs['Color'],bsdf.inputs['Base Color'])
try:validate_principled(mat)
except ValueError as error:assert 'missing/unreadable image' in str(error)
else:raise AssertionError('Missing image accepted')
texture.image=bpy.data.images.new('Valid generated image',width=4,height=4)
validate_principled(mat)
print('PRINCIPLED VALIDATION PASSED: opaque accepted; transmission/alpha/coat/IOR/missing image rejected',flush=True)
