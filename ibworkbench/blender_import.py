"""Inspect ordinary Blender/glTF scenes and apply explicit import assignments."""
import json
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix
from .formats import Mesh, digest
from .new_actor import PROFILE, BASE_MESH, profile_assets
from .import_plan import FORMATS, COLLECTIONS, VISUAL_ROLES, validate_plan, recipe_structure_errors
from .blender_new_actor import validate_principled, build_new_actor
from .socket_types import socket_catalog


def open_source(source):
    source=Path(source).resolve()
    if source.suffix.lower() not in FORMATS:
        raise ValueError('Use a .blend, .glb or .gltf file')
    if source.suffix.lower()=='.blend':
        bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source))
    if bpy.context.object and bpy.context.object.mode!='OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()
    return source


def material_info(material):
    try:
        shader,_=validate_principled(material)
        issue=None
        def value(socket):
            if socket.is_linked:return 'linked'
            number=socket.default_value
            return ', '.join(format(v,'.4g') for v in number) if hasattr(number,'__len__') else format(number,'.4g')
        channels={key:value(shader.inputs[key])
                  for key in ('Base Color','Metallic','Roughness','Normal','Emission Color','Emission Strength')}
    except ValueError as e:
        issue=str(e);channels={}
    images=[];visited=set()
    def walk(tree):
        if not tree or tree.as_pointer() in visited:return
        visited.add(tree.as_pointer())
        for node in tree.nodes:
            if node.type=='TEX_IMAGE':
                image=node.image
                images.append(dict(node=node.name,name=image.name if image else None,
                                   size=list(image.size) if image else [0,0],packed=bool(image and image.packed_file)))
            elif node.type=='GROUP':walk(node.node_tree)
    walk(material.node_tree)
    return dict(name=material.name,issue=issue,channels=channels,images=images,diffuse=list(material.diffuse_color))


def inspect_loaded(source,game):
    assets=profile_assets(game)
    raw=Mesh(assets.resolve(BASE_MESH,'.insm').read_bytes())
    socket_names=[s['name'] for s in raw.sockets]
    objects=[]
    for obj in bpy.context.scene.objects:
        item=dict(name=obj.name,type=obj.type,collections=[c.name for c in obj.users_collection],
                  socket=obj.get('IB_socket') or (obj.name if obj.name in socket_names else None),
                  socket_preset=obj.get('IB_socket_preset',''),socket_group=obj.get('IB_socket_group',0),
                  location=list(obj.matrix_world.translation),dimensions=list(obj.dimensions),slots=[])
        if obj.type=='MESH':
            mesh=obj.data
            item.update(vertices=len(mesh.vertices),faces=len(mesh.polygons),uv_layers=[u.name for u in mesh.uv_layers])
            item['geometry_issue']='Animation, shape keys, constraints or armature deformation are not supported for mesh export.' if (mesh.shape_keys or obj.animation_data or obj.constraints or any(m.type=='ARMATURE' for m in obj.modifiers)) else None
            item['slots']=[dict(index=i,material=slot.material.name if slot.material else None) for i,slot in enumerate(obj.material_slots)] or [dict(index=0,material=None)]
            # A bounded wireframe makes arbitrary names identifiable without
            # embedding a second renderer or loading full geometry in the UI.
            points=[];edges=[]
            # Blender RNA collections support integer indexing, not stepped
            # slices. Ceil division also spreads the sample over the full mesh.
            stride=max(1,(len(mesh.edges)+899)//900)
            for edge_index in range(0,len(mesh.edges),stride):
                edge=mesh.edges[edge_index]
                index=len(points)
                points.extend([list(obj.matrix_world@mesh.vertices[i].co) for i in edge.vertices])
                edges.append([index,index+1])
            item['preview']=dict(points=points,edges=edges)
        objects.append(item)
    return dict(version=1,profile=PROFILE,source=str(source),source_sha256=digest(Path(source).read_bytes()),
                suggested_scale=float(bpy.context.scene.unit_settings.scale_length),objects=objects,
                materials=[material_info(m) for m in bpy.data.materials],sockets=socket_names,socket_catalog=socket_catalog(assets.root))


def inspect_custom(job):
    source=open_source(job['source'])
    report=inspect_loaded(source,job['game'])
    Path(job['report']).write_text(json.dumps(report),encoding='utf8')
    print('INSPECTED',len(report['objects']),'objects;',len(report['materials']),'materials',flush=True)


def assigned_scene(plan,inspection,game):
    errors,warnings=validate_plan(plan,inspection)
    if errors:raise ValueError('\n'.join(errors))
    assets=profile_assets(game)
    raw=Mesh(assets.resolve(BASE_MESH,'.insm').read_bytes())
    objects={o.name:o for o in bpy.context.scene.objects}
    worlds={name:obj.matrix_world.copy() for name,obj in objects.items()}
    # Generated working collections never depend on source names. The loaded
    # scene is temporary; the input file is never saved by this workflow.
    for col in list(bpy.data.collections):col.name='Source - '+col.name
    collections={}
    for name in [*COLLECTIONS.values(),'Sockets','Ignored']:
        collections[name]=bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collections[name])
    conversion={(m['object'],m['slot']):m for m in plan['materials']}
    source_materials={m.name:m for m in bpy.data.materials}
    socket_targets=set()
    scale=Matrix.Scale(plan['scale'],4)
    for entry in plan['objects']:
        obj=objects[entry['name']];role=entry['role']
        obj.parent=None;obj.matrix_world=scale@worlds[entry['name']]
        if obj.get('IB_socket') is not None:del obj['IB_socket']
        for col in list(obj.users_collection):col.objects.unlink(obj)
        collection=COLLECTIONS.get(role,'Ignored')
        collections[collection].objects.link(obj)
        obj.hide_viewport=False;obj.hide_set(False);obj.hide_render=role not in VISUAL_ROLES
        if role in VISUAL_ROLES:
            obj.data=obj.data.copy()
            if not len(obj.data.materials):obj.data.materials.append(bpy.data.materials.new('Unassigned import slot'))
            for i in range(len(obj.material_slots)):
                mapping=conversion[(entry['name'],i)]
                original=source_materials.get(mapping['source_material'])
                if mapping['mode']=='diffuse':
                    mat=bpy.data.materials.new((original.name if original else 'Default grey')+' - color only')
                    mat.use_nodes=True
                    color=list(original.diffuse_color) if original else [.35,.35,.35,1]
                    color[3]=1
                    mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=color
                else:mat=original.copy()
                mat['IB_import_resolution']=mapping['resolution']
                obj.material_slots[i].link='DATA';obj.material_slots[i].material=mat
        elif role=='socket':
            # Socket placement is the chosen object's origin, not its vertices.
            target=entry['socket'];socket_targets.add(target)
            empty=bpy.data.objects.new('Assigned '+target,None)
            collections['Sockets'].objects.link(empty)
            empty.matrix_world=obj.matrix_world.copy()
            empty.scale=(1,1,1);empty['IB_socket']=target
            empty['IB_socket_preset']=entry.get('socket_preset','');empty['IB_socket_group']=entry.get('socket_group',0)
            empty.empty_display_type='ARROWS';empty.empty_display_size=.5
            obj.hide_render=True
    collections['Ignored'].hide_viewport=True;collections['Ignored'].hide_render=True
    for socket in raw.sockets:
        if socket['name'] in socket_targets:continue
        obj=bpy.data.objects.new(socket['name'],None);collections['Sockets'].objects.link(obj)
        p,q=socket['position'],socket['quaternion']
        obj.location=(p[0]*1000,p[2]*1000,p[1]*1000)
        obj.rotation_mode='QUATERNION';obj.rotation_quaternion=(q[3],-q[0],-q[2],-q[1]);obj['IB_socket']=socket['name']
    text=bpy.data.texts.get('IB_NEW_ACTOR.json') or bpy.data.texts.new('IB_NEW_ACTOR.json')
    text.clear();text.write(json.dumps(dict(version=1,profile=PROFILE)))
    bpy.context.scene['IB_actor_name']=plan['name'];bpy.context.scene['IB_bake_resolution']=plan['resolution']
    bpy.context.scene['IB_socket_catalog_sha256']=inspection['socket_catalog']['sha256']
    bpy.context.scene.unit_settings.system='METRIC';bpy.context.scene.unit_settings.scale_length=1
    bpy.context.view_layer.update()
    return warnings


def convert_custom(job):
    plan=job['plan']
    malformed=recipe_structure_errors(plan)
    if malformed:raise ValueError('\n'.join(malformed))
    source=open_source(plan['source'])
    inspection=inspect_loaded(source,job['game'])
    warnings=assigned_scene(plan,inspection,job['game'])
    if job['action']=='prepare-custom':
        output=Path(job['output'])
        if output.exists() or output.suffix.lower()!='.blend':raise ValueError('Choose a new .blend filename')
        bpy.ops.file.pack_all()
        output.parent.mkdir(parents=True,exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(output.resolve()),compress=True)
    else:
        build_new_actor(dict(job,name=plan['name'],import_warnings=warnings),prepared=True)
