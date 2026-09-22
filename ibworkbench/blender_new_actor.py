"""Principled authoring and Cycles baking for a new Interceptor-derived actor."""
import json
import math
import struct
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector, Quaternion
from .formats import Mesh, asset_hash, digest, xml_read
from .new_actor import (PROFILE, SHADER, BASE_ACTOR, BASE_MESH, BASE_COLLISION,
                        actor_name, profile_assets, material_bytes, layout_materials,
                        pack_channels, actor_xml, stage_package)
from .texture_writeback import encode_texture
from .blender_replacement import rebuild_mesh
from .socket_types import socket_catalog, preset_errors, with_sockets, build_socket_assets, COCKPIT_CAMERA


def dummy_template(job):
    name = actor_name(job.get('name','CustomInterceptor'))
    out = Path(job['output'])
    if out.suffix.lower() != '.blend' or out.exists():
        raise ValueError('Choose a new .blend filename')
    assets = profile_assets(job['game'])
    raw = Mesh(assets.resolve(BASE_MESH,'.insm').read_bytes())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    cols = {}
    for label in ('Render','Collision','Sockets'):
        cols[label] = bpy.data.collections.new(label)
        scene.collection.children.link(cols[label])
    def material(label,color,metal,rough,emission=0):
        mat = bpy.data.materials.new(label)
        mat.use_nodes=True
        bsdf=mat.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value=(*color,1)
        bsdf.inputs['Metallic'].default_value=metal
        bsdf.inputs['Roughness'].default_value=rough
        bsdf.inputs['Emission Color'].default_value=(*color,1)
        bsdf.inputs['Emission Strength'].default_value=emission
        mat.diffuse_color=(*color,1)
        return mat
    hull=material('Hull - Principled + linked textures',(.07,.21,.36),.65,.4)
    trim=material('Trim - Principled',(.7,.21,.035),.35,.32)
    glow=material('Engine - Principled emission',(.015,.3,.8),0,.3,3)
    image=bpy.data.images.new('Dummy hull panels',width=64,height=64)
    pixels=np.ones((64,64,4),np.float32)
    yy,xx=np.indices((64,64))
    pixels[:,:,:3]=np.where((((xx//8)+(yy//8))%2)[...,None],np.array([.15,.36,.55]),np.array([.08,.17,.27]))
    image.pixels.foreach_set(pixels.ravel())
    image.pack()
    tex=hull.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image=image
    tex.location=(-500,100)
    hull.node_tree.links.new(tex.outputs['Color'],hull.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    noise=hull.node_tree.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value=5
    noise.location=(-500,-200)
    hull.node_tree.links.new(noise.outputs['Fac'],hull.node_tree.nodes['Principled BSDF'].inputs['Roughness'])
    normal=bpy.data.images.new('Dummy tangent normal',width=32,height=32)
    normal.colorspace_settings.name='Non-Color'
    values=np.ones((32,32,4),np.float32)
    values[:,:,0]=.5+.08*np.sin(np.arange(32)[None,:]*2*math.pi/8)
    values[:,:,1]=.5
    values[:,:,2]=np.sqrt(1-(values[:,:,0]*2-1)**2)*.5+.5
    normal.pixels.foreach_set(values.ravel())
    normal.pack()
    nt=hull.node_tree
    normaltex=nt.nodes.new('ShaderNodeTexImage'); normaltex.image=normal
    normaltex.location=(-700,-450)
    normalnode=nt.nodes.new('ShaderNodeNormalMap'); normalnode.location=(-250,-300)
    nt.links.new(normaltex.outputs['Color'],normalnode.inputs['Color'])
    nt.links.new(normalnode.outputs['Normal'],nt.nodes['Principled BSDF'].inputs['Normal'])
    def box(label,location,scale,mat,collection='Render'):
        bpy.ops.mesh.primitive_cube_add(size=2,location=location)
        obj=bpy.context.object; obj.name=label; obj.scale=scale
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
        for col in list(obj.users_collection): col.objects.unlink(obj)
        cols[collection].objects.link(obj)
        if mat: obj.data.materials.append(mat)
        return obj
    main=box('Hull',(0,0,0),(1.8,5.8,.8),hull)
    # Taper the forward hull while keeping the dummy easy to edit.
    for v in main.data.vertices:
        if v.co.y > 0: v.co.x*=.4; v.co.z*=.6
    box('Left wing',(-3,0,0),(1.5,2.7,.2),trim)
    box('Right wing',(3,0,0),(1.5,2.7,.2),trim)
    box('Engine glow',(0,-5.85,0),(1.35,.08,.55),glow)
    collision=box('Collision hull',(0,0,0),(4.6,6,1),None,'Collision')
    collision.display_type='WIRE'; collision.hide_render=True
    for socket in raw.sockets:
        o=bpy.data.objects.new(socket['name'],None)
        cols['Sockets'].objects.link(o)
        p=socket['position']; q=socket['quaternion']
        o.location=(p[0]*1000,p[2]*1000,p[1]*1000)
        o.rotation_mode='QUATERNION'; o.rotation_quaternion=(q[3],-q[0],-q[2],-q[1])
        o['IB_socket']=socket['name']; o.empty_display_type='ARROWS'; o.empty_display_size=.25
    scene['IB_actor_name']=name
    scene['IB_bake_resolution']=512
    bpy.data.texts.new('IB_NEW_ACTOR.json').write(json.dumps(dict(version=1,profile=PROFILE,base_actor=BASE_ACTOR),indent=2))
    bpy.data.texts.new('START HERE.txt').write(
        'NEW ACTOR TEMPLATE\n\nEdit or replace meshes in Render. Use one directly connected Principled BSDF per material. '
        'Linked images, Normal Map/Bump, and procedural color/roughness/metallic networks are baked by Workbench. '
        'Use opaque metallic/roughness materials; transparency, transmission, coat, sheen, subsurface and displacement are not supported by this profile.\n\n'
        'Edit the Collision hull separately. Reposition the named socket empties for guns/thrusters. Keep their names. '
        'Scene custom properties: IB_actor_name is the unique new actor name; IB_bake_resolution is per-material texture size (128..2048).\n\n'
        'Save, then use Workbench: New actor .blend -> mod folder. The converter unwraps a separate bake UV map and writes new assets. '
        'Team skins/paint are disabled. Interceptor flight/loadout behavior is inherited. No custom cockpit or LODs are generated in this first profile. '
        'The staged actor still needs an in-game spawn test; staging does not install it.\n')
    for o in bpy.context.selected_objects:o.select_set(False)
    main.select_set(True);bpy.context.view_layer.objects.active=main
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.region_3d.view_distance=22
                area.spaces.active.shading.color_type='MATERIAL'
    out.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out.resolve()),compress=True)
    print('NEW ACTOR TEMPLATE',out,flush=True)


def combine_collection(name):
    col=bpy.data.collections.get(name)
    if col is None:raise ValueError('Missing collection: '+name)
    originals=[o for o in col.all_objects if o.type=='MESH']
    if not originals:raise ValueError(name+' needs at least one mesh')
    for o in bpy.context.selected_objects:o.select_set(False)
    copies=[]
    graph=bpy.context.evaluated_depsgraph_get()
    for src in originals:
        if src.data.shape_keys or src.animation_data or src.constraints or any(m.type=='ARMATURE' for m in src.modifiers):
            raise ValueError(src.name+': animation/shape keys/constraints/armature deformation are unsupported')
        data=bpy.data.meshes.new_from_object(src.evaluated_get(graph),preserve_all_data_layers=True,depsgraph=graph)
        if data.uv_layers:
            uvvalues=np.empty((len(data.loops),2),np.float32)
            data.uv_layers.active.data.foreach_get('uv',uvvalues.ravel())
            source_uv=data.uv_layers.get('IB_SourceUV') or data.uv_layers.new(name='IB_SourceUV')
            source_uv.data.foreach_set('uv',uvvalues.ravel())
        else:data.uv_layers.new(name='IB_SourceUV')
        coordinates=np.empty((len(data.vertices),3),np.float32)
        data.vertices.foreach_get('co',coordinates.ravel())
        if not len(coordinates):raise ValueError(src.name+': empty mesh')
        low,high=coordinates.min(axis=0),coordinates.max(axis=0)
        for attr_name,values in (('IB_SourcePosition',coordinates),('IB_SourceGenerated',(coordinates-low)/np.maximum(high-low,1e-20))):
            attribute=data.attributes.get(attr_name) or data.attributes.new(name=attr_name,type='FLOAT_VECTOR',domain='POINT')
            attribute.data.foreach_set('vector',values.ravel())
        data.transform(src.matrix_world)
        if src.matrix_world.determinant()<0:data.flip_normals()
        obj=bpy.data.objects.new('Bake '+src.name,data)
        bpy.context.scene.collection.objects.link(obj)
        obj.select_set(True);copies.append(obj)
        src.hide_render=True
    bpy.context.view_layer.objects.active=copies[0]
    if len(copies)>1:bpy.ops.object.join()
    obj=copies[0]
    obj.name='Converted '+name
    obj.data.uv_layers.active=obj.data.uv_layers['IB_SourceUV']
    bpy.context.view_layer.update()
    return obj


def validate_principled(mat):
    if mat is None or not mat.use_nodes:
        raise ValueError('Every render slot needs a node material with Principled BSDF')
    tree=mat.node_tree
    output=next((n for n in tree.nodes if n.type=='OUTPUT_MATERIAL' and n.is_active_output),None)
    if output is None or not output.inputs['Surface'].is_linked:
        raise ValueError(mat.name+': connect Principled BSDF directly to Material Output')
    shader=output.inputs['Surface'].links[0].from_node
    if shader.type!='BSDF_PRINCIPLED':
        raise ValueError(mat.name+': this profile requires a directly connected Principled BSDF')
    for socket in ('Volume','Displacement'):
        if output.inputs[socket].is_linked:raise ValueError(mat.name+': '+socket+' is not supported')
    expected={'Alpha':1,'Transmission Weight':0,'Coat Weight':0,'Sheen Weight':0,'Subsurface Weight':0,
              'Anisotropic':0,'Thin Film Thickness':0,'IOR':1.5,'Specular IOR Level':.5,'Diffuse Roughness':0}
    for key,value in expected.items():
        s=shader.inputs.get(key)
        if s and (s.is_linked or abs(s.default_value-value)>1e-5):
            raise ValueError(mat.name+': '+key+' cannot be represented by the Interceptor profile (expected '+str(value)+')')
    tint=shader.inputs.get('Specular Tint')
    if tint and (tint.is_linked or any(abs(v-1)>1e-5 for v in tint.default_value)):
        raise ValueError(mat.name+': tinted specular is not supported by this profile')
    visited=set()
    def check_images(node):
        if node.as_pointer() in visited:return
        visited.add(node.as_pointer())
        if node.type=='TEX_IMAGE':
            image=node.image
            if image is None or image.size[0]==0 or image.size[1]==0:
                raise ValueError(mat.name+': missing/unreadable image in '+node.name)
            if image.source not in ('FILE','GENERATED'):
                raise ValueError(mat.name+': use a static 2D image in '+node.name)
        if node.type=='GROUP' and node.node_tree:
            for output_node in node.node_tree.nodes:
                if output_node.type=='GROUP_OUTPUT':check_images(output_node)
        for socket in node.inputs:
            for link in socket.links:check_images(link.from_node)
    check_images(shader)
    return shader,output


def lock_coordinates(tree,original_uv,visited=None):
    visited={} if visited is None else visited
    uv=tree.nodes.new('ShaderNodeUVMap');uv.uv_map=original_uv
    attributes={}
    for label,name in (('Generated','IB_SourceGenerated'),('Object','IB_SourcePosition')):
        node=tree.nodes.new('ShaderNodeAttribute');node.attribute_name=name
        attributes[label]=node.outputs['Vector']
    for node in list(tree.nodes):
        if node.type=='TEX_IMAGE' and not node.inputs['Vector'].is_linked:
            tree.links.new(uv.outputs['UV'],node.inputs['Vector'])
        if node.type in ('TEX_NOISE','TEX_VORONOI','TEX_WAVE','TEX_GRADIENT','TEX_CHECKER','TEX_BRICK','TEX_MAGIC') and not node.inputs['Vector'].is_linked:
            tree.links.new(attributes['Generated'],node.inputs['Vector'])
        if node.type=='TEX_COORD':
            for label,source in [('UV',uv.outputs['UV']),*attributes.items()]:
                if label=='Object' and node.object is not None:continue
                for link in list(node.outputs[label].links):tree.links.new(source,link.to_socket)
        if node.type=='NORMAL_MAP' and not node.uv_map:node.uv_map=original_uv
        if node.type=='GROUP' and node.node_tree:
            original=node.node_tree
            if original.as_pointer() not in visited:
                copied=original.copy();visited[original.as_pointer()]=copied
                lock_coordinates(copied,original_uv,visited)
            node.node_tree=visited[original.as_pointer()]


def bake_materials(obj,resolution):
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name='UVMap')
    original_uv=obj.data.uv_layers.active.name
    # Lock source texture coordinates before selecting the new target UV map.
    mats=[]
    for slot in obj.material_slots:
        validate_principled(slot.material)
        slot.material=slot.material.copy()
        mat=slot.material
        shader,output=validate_principled(mat)
        tree=mat.node_tree
        lock_coordinates(tree,original_uv)
        target=tree.nodes.new('ShaderNodeTexImage')
        mats.append((mat,shader,output,target))
    if not mats:raise ValueError('Render mesh needs at least one Principled material')
    layer=obj.data.uv_layers.new(name='IB_BakeUV')
    bake_uv=layer.name
    obj.data.uv_layers.active=layer
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66),island_margin=.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    layer=obj.data.uv_layers[bake_uv]
    for uv in obj.data.uv_layers:uv.active_render=uv==layer
    scene=bpy.context.scene
    scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=8
    scene.render.bake.use_selected_to_active=False
    samples=[{} for _ in mats]
    for channel in ('Base Color','Roughness','Metallic','Emission','Normal'):
        images=[];temporary=[]
        for i,(mat,shader,output,target) in enumerate(mats):
            tree=mat.node_tree
            size=int(mat.get('IB_import_resolution',resolution))
            if size not in (128,256,512,1024,2048):raise ValueError(mat.name+': invalid texture resolution')
            image=bpy.data.images.new('Bake '+channel,width=size,height=size,float_buffer=True,alpha=True)
            image.colorspace_settings.name='Non-Color';target.image=image
            tree.nodes.active=target
            for n in tree.nodes:n.select=n==target
            if channel!='Normal':
                emit=tree.nodes.new('ShaderNodeEmission');temporary.append((tree,emit))
                source=shader.inputs['Emission Color' if channel=='Emission' else channel]
                if source.is_linked:tree.links.new(source.links[0].from_socket,emit.inputs['Color'])
                else:
                    value=source.default_value
                    emit.inputs['Color'].default_value=list(value) if hasattr(value,'__len__') else (value,value,value,1)
                if channel=='Emission':
                    strength=shader.inputs['Emission Strength']
                    if strength.is_linked:tree.links.new(strength.links[0].from_socket,emit.inputs['Strength'])
                    else:emit.inputs['Strength'].default_value=strength.default_value
                tree.links.new(emit.outputs[0],output.inputs['Surface'])
            else:tree.links.new(shader.outputs[0],output.inputs['Surface'])
            images.append(image)
        print('BAKE',channel,'sizes',', '.join(str(im.size[0])+'x'+str(im.size[1]) for im in images),'materials',len(mats),flush=True)
        bpy.ops.object.bake(type='NORMAL' if channel=='Normal' else 'EMIT',uv_layer=bake_uv,margin=8,use_clear=True)
        for i,image in enumerate(images):
            pixels=np.empty((image.size[1],image.size[0],4),np.float32)
            image.pixels.foreach_get(pixels.ravel())
            samples[i][channel]=pixels[::-1,:,:3].copy()
            mats[i][3].image=None
            bpy.data.images.remove(image)
        for tree,node in temporary:tree.nodes.remove(node)
    for mat,shader,output,target in mats:mat.node_tree.links.new(shader.outputs[0],output.inputs['Surface'])
    # Game geometry references the atlas, not the original source UV layout.
    uvvalues=np.empty((len(obj.data.loops),2),np.float32)
    obj.data.uv_layers[bake_uv].data.foreach_get('uv',uvvalues.ravel())
    for uv in list(obj.data.uv_layers):obj.data.uv_layers.remove(uv)
    obj.data.uv_layers.new(name='UV0').data.foreach_set('uv',uvvalues.ravel())
    return samples


def build_new_actor(job,prepared=False):
    if not prepared:bpy.ops.wm.open_mainfile(filepath=job['blend'],load_ui=False,use_scripts=False)
    text=bpy.data.texts.get('IB_NEW_ACTOR.json')
    if text is None:raise ValueError('Use a New Actor template, not a replacement export')
    manifest=json.loads(text.as_string())
    if manifest.get('version')!=1 or manifest.get('profile')!=PROFILE:raise ValueError('Unsupported new actor profile')
    name=actor_name(job.get('name') or bpy.context.scene.get('IB_actor_name'))
    resolution=int(bpy.context.scene.get('IB_bake_resolution',512))
    if resolution not in (128,256,512,1024,2048):raise ValueError('Bake resolution must be 128, 256, 512, 1024 or 2048')
    if Path(job['output']).exists():raise ValueError('Choose a new output directory')
    assets=profile_assets(job['game'])
    raw=Mesh(assets.resolve(BASE_MESH,'.insm').read_bytes())
    sockets={};socket_settings=[]
    for obj in bpy.context.scene.objects:
        key=obj.get('IB_socket')
        if not key:continue
        if obj.get('IB_socket_preset')==COCKPIT_CAMERA and obj.type!='EMPTY':
            raise ValueError('Cockpit_Camera_Position must be assigned to an Empty')
        if key in sockets:raise ValueError('Duplicate socket: '+key)
        pos,q,scale=obj.matrix_world.decompose()
        if any(abs(x-1)>1e-5 for x in scale):raise ValueError('Socket scaling is unsupported: '+key)
        sockets[key]=[pos.x/1000,pos.z/1000,pos.y/1000,-q.x,-q.z,-q.y,q.w]
        socket_settings.append(dict(socket=key,socket_preset=obj.get('IB_socket_preset',''),socket_group=obj.get('IB_socket_group',0)))
    base_sockets={s['name'] for s in raw.sockets}
    if not base_sockets.issubset(sockets):raise ValueError('Keep all template socket names, exactly once')
    typed=any(s['socket_preset'] for s in socket_settings)
    catalog=socket_catalog(assets.root) if typed else dict(presets=[])
    errors=preset_errors(socket_settings,catalog,base_sockets)
    if errors:raise ValueError('\n'.join(errors))
    if typed and bpy.context.scene.get('IB_socket_catalog_sha256')!=catalog['sha256']:
        raise ValueError('Game attachment definitions changed. Reinspect and reassign socket types in Import custom meshes.')
    for obj in bpy.context.scene.objects:obj.hide_render=True
    payload={};registrations=[]
    def add(logical,suffix,data):
        ref='Dev/Mods/'+name+'/'+suffix[1:]+'/'+f'{asset_hash(logical):08x}'+suffix
        payload[ref]=data;registrations.append((logical,ref));return ref
    notes=list(job.get('import_warnings',[]))
    textures={'skin':0xf35b29a0,'data':0x255f15b2,'normal':0x35ed2a67}
    bounds=[]
    def has_mesh(collection):
        col=bpy.data.collections.get(collection)
        return col is not None and any(o.type=='MESH' for o in col.all_objects)
    def export_visual(collection):
        obj=combine_collection(collection)
        samples=bake_materials(obj,resolution)
        ids=[]
        for i,sample in enumerate(samples):
            skin,data,normal,power,adapted=pack_channels(sample['Base Color'],sample['Roughness'][:,:,0],sample['Metallic'][:,:,0],sample['Emission'],sample['Normal'])
            texture_ids={}
            # Keep the original template's material names stable.
            prefix=f'Mods/{name}/'+('' if collection=='Render' else collection+'/')+f'Material{i}'
            for label,pixels,dxgi in (('skin',skin,29),('data',data,28),('normal',normal,31)):
                logical=prefix+'/'+label;texture_ids[label]=asset_hash(logical)
                header=bytearray(assets.resolve(textures[label],'.txb').read_bytes()[:56])
                struct.pack_into('<I',header,28,dxgi)
                add(logical,'.txb',encode_texture(bytes(header),np.clip(pixels,0,1)))
            params={'S_EmissivePower':('scalar',power),'S_AO_Blend':('scalar',1),
                    'SP_DetailRoughnessStrength':('scalar',0),'V_DetailColorStrength':('vector',[0,0,0,0]),
                    'S_DetailTiling':('scalar',1),'T_Skin':('texture',texture_ids['skin']),
                    'T_Data':('texture',texture_ids['data']),
                    '_inovae_tex2d_35ed2a67':('texture',texture_ids['normal'])}
            ids.append(asset_hash(prefix));add(prefix,'.cmti',material_bytes(params))
            if adapted:notes.append(collection+' material '+str(i)+': glow color adapted into luminous albedo texels.')
        layout=layout_materials(raw,ids)
        if collection=='Render':layout=with_sockets(layout,sockets)
        else:
            data=bytearray(layout.data[:layout.index_start+layout.ni*layout.width+len(layout.groups)*45])
            struct.pack_into('<I',data,18,0);layout=Mesh(data)
        logical=f'Mods/{name}/{collection}'
        add(logical,'.insm',rebuild_mesh(obj,layout))
        bounds.extend([list(obj.matrix_world@Vector(v)) for v in obj.bound_box])
        obj.hide_render=True
        return logical
    def export_collision(collection):
        obj=combine_collection(collection)
        for polygon in obj.data.polygons:polygon.material_index=0
        ref=add(f'Mods/{name}/{collection}','.insm',rebuild_mesh(obj,Mesh(assets.path(BASE_COLLISION).read_bytes())))
        bounds.extend([list(obj.matrix_world@Vector(v)) for v in obj.bound_box]);obj.hide_render=True
        return ref
    render_logical=export_visual('Render')
    collision_ref=export_collision('Collision')
    lods={i:export_visual('LOD'+str(i)) for i in range(1,7) if has_mesh('LOD'+str(i))}
    if lods and sorted(lods)!=list(range(1,max(lods)+1)):raise ValueError('LOD levels must be consecutive starting at 1')
    exterior=export_visual('ExteriorCockpit') if has_mesh('ExteriorCockpit') else None
    interior=export_visual('InteriorCockpit') if has_mesh('InteriorCockpit') else None
    cockpit_collision=export_collision('CockpitCollision') if has_mesh('CockpitCollision') else None
    if cockpit_collision and not interior:raise ValueError('Cockpit collision needs an interior cockpit')
    xml=actor_xml(assets.root,name,render_logical,collision_ref,bounds)
    from .new_actor import add_mesh_roles
    cockpit_template=xml_read(assets.path(BASE_ACTOR)).find('CClientInternalCockpitComponent')
    add_mesh_roles(xml,lods,exterior,interior,cockpit_collision,cockpit_template)
    registry_updates={}
    if typed:
        attachment_payload,registry_updates,attachment_notes=build_socket_assets(assets.root,name,xml,sockets,socket_settings,catalog)
        payload.update(attachment_payload);notes+=attachment_notes
        render_ref=next(ref for logical,ref in registrations if logical==render_logical)
        payload[render_ref]=with_sockets(Mesh(payload[render_ref]),sockets).data
    equipment=any(s['socket_preset'] and s['socket_preset']!=COCKPIT_CAMERA for s in socket_settings)
    notes += [('Interceptor flight defaults inherited; attachment presets use a generated default loadout.' if equipment else 'Interceptor gameplay/loadouts and named sockets inherited;')+' Team skins and paint disabled.',
              'First profile: opaque Principled metallic/roughness surfaces. AO defaults to 1; AO already multiplied into base color is baked there.',
              'LOD and cockpit geometry is exported only when assigned; no LOD meshes are generated automatically.',
              'Uncompressed RGBA8 textures with mipmaps. In-game actor spawning/rendering still requires validation.']
    report=stage_package(assets.root,name,job['output'],payload,registrations,xml,notes,registry_updates,
                         {ref:catalog['sources'][ref] for ref in registry_updates})
    print('NEW ACTOR STAGED',name,len(report['files']),'files',job['output'],flush=True)
