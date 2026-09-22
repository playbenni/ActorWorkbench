"""Blender: compare authored and exported albedo using the staged TXB bytes."""
import sys, json, struct
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ibworkbench.formats import Mesh, asset_hash, material_instance

base=Path(__file__).resolve().parent.parent
out=base/'samples/new-actor-preview';out.mkdir(exist_ok=True)
blend=base.parent/'Modfolder/CustomInterceptor.blend'
mod=base.parent/'Modfolder/CustomInterceptor_Mod/payload/Dev/Mods/CustomInterceptor'
for mode in ('authored','converted'):
    bpy.ops.wm.open_mainfile(filepath=str(blend),load_ui=False,use_scripts=False)
    scene=bpy.context.scene
    objects=list(bpy.data.collections['Render'].objects)
    for o in scene.objects:o.hide_render=o not in objects
    if mode=='authored':
        for mat in {o.active_material for o in objects}:
            tree=mat.node_tree;shader=tree.nodes.get('Principled BSDF');output=tree.nodes.get('Material Output')
            emit=tree.nodes.new('ShaderNodeEmission');source=shader.inputs['Base Color']
            if source.is_linked:tree.links.new(source.links[0].from_socket,emit.inputs['Color'])
            else:emit.inputs['Color'].default_value=source.default_value
            tree.links.new(emit.outputs[0],output.inputs['Surface'])
    else:
        for o in objects:o.hide_render=True
        raw=Mesh((mod/'insm'/f'{asset_hash("Mods/CustomInterceptor/Render"):08x}.insm').read_bytes())
        mesh=bpy.data.meshes.new('Exported mesh')
        mesh.from_pydata((raw.positions[:,[0,2,1]]*1000).tolist(),[],raw.faces.tolist())
        uv=raw.attribute(8)[raw.faces.ravel()].copy();uv[:,1]=1-uv[:,1]
        mesh.uv_layers.new(name='UV0').data.foreach_set('uv',uv.ravel())
        for i,group in enumerate(raw.groups):
            _,params=material_instance((mod/'cmti'/f'{group["material"]:08x}.cmti').read_bytes())
            tex=(mod/'txb'/f'{params["T_Skin"]["value"]:08x}.txb').read_bytes()
            w,h=struct.unpack_from('<2I',tex,4)
            rgba=np.frombuffer(tex,np.uint8,count=w*h*4,offset=56).reshape(h,w,4).astype(np.float32)/255
            rgb=rgba[:,:,:3]
            rgba[:,:,:3]=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
            image=bpy.data.images.new('Exported skin',width=w,height=h,float_buffer=True)
            image.colorspace_settings.name='Non-Color';image.alpha_mode='CHANNEL_PACKED'
            image.pixels.foreach_set(rgba[::-1].copy().ravel())
            mat=bpy.data.materials.new('Exported '+str(i));mat.use_nodes=True
            tree=mat.node_tree;emit=tree.nodes.new('ShaderNodeEmission');node=tree.nodes.new('ShaderNodeTexImage');node.image=image
            tree.links.new(node.outputs['Color'],emit.inputs['Color'])
            tree.links.new(emit.outputs[0],tree.nodes['Material Output'].inputs['Surface'])
            mesh.materials.append(mat)
            for p in mesh.polygons[group['first']//3:(group['first']+group['count'])//3]:p.material_index=i
        obj=bpy.data.objects.new('Exported actor',mesh);scene.collection.objects.link(obj)
    cam=bpy.data.objects.new('Validation camera',bpy.data.cameras.new('Validation camera'))
    scene.collection.objects.link(cam)
    cam.location=(15,20,16);cam.rotation_euler=(-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.type='ORTHO';cam.data.ortho_scale=18;scene.camera=cam
    scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.use_denoising=False
    scene.render.resolution_x=768;scene.render.resolution_y=768;scene.render.resolution_percentage=100
    scene.render.film_transparent=True;scene.render.image_settings.file_format='PNG'
    scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
    scene.render.filepath=str(out/(mode+'.png'))
    bpy.ops.render.render(write_still=True)
    print('ALBEDO CHECK',mode,flush=True)
