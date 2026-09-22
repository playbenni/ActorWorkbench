"""Runs inside Blender only, with automatic execution of blend scripts disabled."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import json
import math
import struct
import traceback
import xml.etree.ElementTree as ET
import numpy as np
import bpy
from mathutils import Quaternion, Vector
from ibworkbench.formats import Mesh, inside, digest, xml_read
from ibworkbench.mods import atomic_write
from ibworkbench.blender_replacement import rebuild_mesh, replacement_objects, texture_edits

LIGHT_FIX = Quaternion((1,0,0), math.pi/2)


def graph_signature(material):
    result = []
    for node in material.node_tree.nodes:
        values = []
        for socket in node.inputs:
            if hasattr(socket, 'default_value'):
                v = socket.default_value
                if isinstance(v, (float,int,str,bool)):
                    values.append((socket.identifier, v))
                elif hasattr(v, '__len__'):
                    values.append((socket.identifier,list(v)))
        config = {k:getattr(node,k) for k in ('operation','blend_type','uv_map','extension','interpolation','projection') if hasattr(node,k)}
        image = getattr(node,'image',None)
        result.append((node.name, node.bl_idname, values, image.name if image else None,
                       image.colorspace_settings.name if image else None,config))
    links = sorted((l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in material.node_tree.links)
    return json.dumps((result,links),sort_keys=True)


def material_create(item, textures):
    mat = bpy.data.materials.new('IB '+item['id'])
    mat.use_nodes = True
    mat['IB_material'] = item['id']
    mat['IB_shader_approximation'] = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get('Principled BSDF')
    bsdf.inputs['Roughness'].default_value = .55
    params = item['params']
    base_candidates = ('IB_RuntimeColorMap','T_ColourSkin','T_Skin','T_Color_Roughness','Color_Roughness','Bcol_Rough','Colour','T_Colour','T_Color','T_Albedo','T_Diffuse','Diffuse','BaseColor')
    chosen = next((name for name in base_candidates if name in params and params[name].get('texture') in textures), None)
    for index, (name, param) in enumerate(params.items()):
        if name in item['editable'] and param['kind'] != 'texture':
            mat['IB_param_'+name] = param['value']
        if param['kind'] == 'texture':
            image = textures.get(param.get('texture'))
            if image is None:
                continue
            node = nodes.new('ShaderNodeTexImage')
            node.name = name
            node.label = name+' (game parameter)'
            node.image = image
            uv = nodes.get('Game UV0')
            if uv is None:
                uv = nodes.new('ShaderNodeUVMap')
                uv.name = 'Game UV0'
                uv.uv_map = 'UV0'
            links.new(uv.outputs['UV'],node.inputs['Vector'])
            node.location = (-650, -250*index)
            if name == chosen:
                links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
                if name in ('T_Color_Roughness','Color_Roughness','Bcol_Rough'):
                    links.new(node.outputs['Alpha'],bsdf.inputs['Roughness'])
            if name in ('T_Normals','T_Normal','Normals','Normal'):
                linear = image.copy()
                linear.name = image.name+' normal data'
                linear.colorspace_settings.name = 'Non-Color'
                node.image = linear
                split = nodes.new('ShaderNodeSeparateXYZ')
                links.new(node.outputs['Color'],split.inputs[0])
                invert = nodes.new('ShaderNodeMath')
                invert.operation = 'SUBTRACT'
                invert.inputs[0].default_value = 1
                links.new(split.outputs['Y'],invert.inputs[1])
                combine = nodes.new('ShaderNodeCombineXYZ')
                links.new(split.outputs['X'],combine.inputs['X'])
                links.new(invert.outputs[0],combine.inputs['Y'])
                links.new(split.outputs['Z'],combine.inputs['Z'])
                normal = nodes.new('ShaderNodeNormalMap')
                normal.uv_map = 'UV0'
                links.new(combine.outputs[0],normal.inputs['Color'])
                links.new(normal.outputs[0],bsdf.inputs['Normal'])
            # Packed T_Data channel meanings differ by compiled shader. Keep
            # correct image/UV binding but do not invent roughness/normal channels.
        elif param['kind'] in ('scalar','vector'):
            node = nodes.new('ShaderNodeValue' if param['kind']=='scalar' else 'ShaderNodeRGB')
            node.name = 'Game parameter: '+name
            node.label = name+' (metadata; edit IB_param property for write-back)'
            node.outputs[0].default_value = param['value']
            node.location = (-1000, -120*index)
    mat['IB_graph_baseline'] = graph_signature(mat)
    return mat


def normals_signature(mesh):
    values = np.empty((len(mesh.corner_normals),3),dtype=np.float32)
    mesh.corner_normals.foreach_get('vector',values.ravel())
    return digest(np.rint(values*10000).astype(np.int32).tobytes())


def make_mesh(source, item, game, materials):
    raw = Mesh(inside(game,source).read_bytes())
    mesh = bpy.data.meshes.new(Path(source).stem)
    verts = raw.positions[:,[0,2,1]] * 1000
    # The source triangle list is clockwise relative to its stored normals.
    # The x,z,y reflection already reverses handedness: keep index ordering.
    faces = raw.faces
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set('co', verts.ravel())
    mesh.loops.add(faces.size)
    mesh.loops.foreach_set('vertex_index', faces.ravel())
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set('loop_start', np.arange(0,faces.size,3,dtype=np.int32))
    mesh.polygons.foreach_set('loop_total', np.full(len(faces),3,dtype=np.int32))
    mesh.update()
    if item['materials']:
        for key in item['materials']:
            mesh.materials.append(materials[key])
        ids = np.zeros(len(faces),dtype=np.int32)
        for i, group in enumerate(raw.groups):
            ids[group['first']//3:(group['first']+group['count'])//3] = i
        mesh.polygons.foreach_set('material_index',ids)
    for slot in range(8, 16):
        uv = raw.attribute(slot)
        if uv is not None and uv.shape[1] == 2:
            layer = mesh.uv_layers.new(name='UV'+str(slot-8))
            # DirectX UV v-down -> Blender v-up.
            values = uv[faces.ravel()].copy()
            values[:,1] = 1-values[:,1]
            layer.data.foreach_set('uv',values.ravel())
    normal = raw.attribute(3)
    if normal is not None:
        mesh.polygons.foreach_set('use_smooth',np.ones(len(faces),dtype=bool))
        mesh.normals_split_custom_set_from_vertices(normal[:,[0,2,1]])
    colors = raw.attribute(5)
    if colors is not None and raw.types[5] == 7:
        layer = mesh.color_attributes.new(name='Game vertex color',type='BYTE_COLOR',domain='POINT')
        layer.data.foreach_set('color_srgb',(colors/255).ravel())
    mesh['IB_source'] = source
    mesh['IB_normals_baseline'] = normals_signature(mesh)
    return mesh


def export(job):
    project = json.loads(Path(job['manifest']).read_text('utf8'))
    game = Path(job['game'])
    for source, expected in project['sources'].items():
        if digest(inside(game,source).read_bytes()) != expected:
            raise ValueError('Source changed during export: '+source)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    textures = {}
    for key, item in project['textures'].items():
        if item.get('png'):
            img = bpy.data.images.load(item['png'])
            img.name = 'IB texture '+key
            img.pack()
            img['IB_texture'] = key
            item['packed_sha256'] = digest(img.packed_file.data)
            img.filepath = '//textures/'+key+'.png'
            textures[key] = img
    materials = {key:material_create(item,textures) for key,item in project['materials'].items()}
    meshes = {}
    collections = {}
    for name in ('Assembly','Render','Collision','Cockpit','Sockets and effects'):
        col = bpy.data.collections.new(name)
        scene.collection.children.link(col)
        collections[name] = col
    objects = {}
    for item in project['nodes']:
        kind = item['kind']
        data = None
        category = 'Assembly'
        if kind == 'mesh':
            ref = item['mesh']
            if ref not in meshes:
                print('BLENDER MESH',ref,flush=True)
                meshes[ref] = make_mesh(ref,project['meshes'][ref],game,materials)
            data = meshes[ref]
            category = 'LOD '+item.get('level','1') if item['role']=='LOD' else item['role']
        elif kind == 'light':
            data = bpy.data.lights.new(item['name'], 'SPOT' if 'spot' in item['light_type'].lower() else 'POINT')
            data.color = item['color']
            # Photometric conversion is a preview convention, not engine parity.
            data.energy = max(0,item['lumens'])/683
            data.shadow_soft_size = .1
            if data.type == 'SPOT':
                data.spot_size = math.radians(max(1,min(179,item['cone'])))
                data.spot_blend = 1-min(1,item['inner']/max(item['cone'],1))
            category = 'Sockets and effects'
        elif kind in ('socket','effect'):
            category = 'Sockets and effects'
        if category not in collections:
            col = bpy.data.collections.new(category)
            scene.collection.children.link(col)
            collections[category] = col
        obj = bpy.data.objects.new(item['name'],data)
        collections[category].objects.link(obj)
        objects[item['id']] = obj
        if item['parent'] is not None:
            obj.parent = objects[item['parent']]
        obj.location = item['position']
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = item['quaternion']
        if kind == 'light':
            obj.rotation_quaternion = obj.rotation_quaternion @ LIGHT_FIX
        obj.scale = item['scale']
        obj['IB_id'] = item['id']
        obj['IB_kind'] = kind
        if kind == 'socket':
            obj.empty_display_type = 'ARROWS'
        elif data is None:
            obj.empty_display_type = 'PLAIN_AXES'
        obj.empty_display_size = .5
        if 'raw_xml' in item:
            obj['IB_source_xml'] = item['raw_xml']
        if kind == 'mesh' and item['role'] == 'Collision':
            obj.display_type = 'WIRE'
        item['baseline'] = dict(position=list(obj.location),quaternion=list(obj.rotation_quaternion),scale=list(obj.scale))
        if kind == 'light':
            item['light_baseline'] = dict(color=list(data.color),energy=data.energy,type=data.type,
                cone=getattr(data,'spot_size',0),blend=getattr(data,'spot_blend',0))
    for name, col in collections.items():
        if name in ('Collision','Cockpit') or name.startswith('LOD '):
            col.hide_render = True
            scene.view_layers[0].layer_collection.children[name].hide_viewport = True
    for source in project['sources']:
        if source.lower().endswith('.xml'):
            text = bpy.data.texts.new('Original XML: '+source)
            text.write(inside(game,source).read_text('utf-8-sig'))
    readme = bpy.data.texts.new('READ ME - Actor Workbench')
    readme.write('Actor Workbench experimental export. Units: meters, Blender Z up.\n'
        'Render visible; enable Collision, Cockpit and each LOD collection separately.\n'
        'Write-back: arbitrary static topology/UVs and modifiers are supported; retain game material slots and object hierarchy.\n'
        'Replace geometry in Edit Mode, or add a mesh named REPLACE:<exact exported object name>. Keep the original as its target.\n'
        'Replace LOD and Collision objects too when changing the whole actor shape. Reuse original game materials.\n'
        'Material custom IB_param_* properties control editable original scalar/vector parameters.\n'
        'Paint/pack images or replace images in existing texture nodes; arbitrary shader edits are unsupported.\n'
        'Do not edit the manifest or original XML text blocks.\n\n'+'\n'.join(project['warnings']))
    manifest = bpy.data.texts.new('IB_ACTOR_MANIFEST.json')
    manifest.write(json.dumps(project))
    scene.world = bpy.data.worlds.new('Neutral preview')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.18,.18,.18,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .5
    bpy.context.view_layer.update()
    visible = [o for o in objects.values() if o.type=='MESH' and not o.hide_get()]
    if visible:
        corners = [o.matrix_world @ Vector(v) for o in visible for v in o.bound_box]
        low = Vector(tuple(min(v[i] for v in corners) for i in range(3)))
        high = Vector(tuple(max(v[i] for v in corners) for i in range(3)))
        center, radius = (low+high)/2, max((high-low).length/2,1)
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.spaces.active.region_3d.view_location = center
                    area.spaces.active.region_3d.view_distance = radius*2.6
                    area.spaces.active.clip_end = radius*30
                    area.spaces.active.clip_start = max(.005,radius/10000)
                    area.spaces.active.shading.type = 'MATERIAL'
    destination = Path(job['output'])
    if destination.exists():
        raise ValueError('Output already exists; choose a new .blend filename')
    bpy.ops.wm.save_as_mainfile(filepath=str(destination),compress=True)
    print('EXPORT COMPLETE',destination,flush=True)


def object_values(obj, item):
    q = obj.rotation_quaternion.copy()
    if item['kind'] == 'light':
        q = q @ LIGHT_FIX.inverted()
    return list(obj.location), list(q), list(obj.scale)


def close(a,b):
    return np.allclose(a,b,rtol=1e-6,atol=1e-7)


def vertex_edits(obj, raw):
    mesh = obj.data
    if obj.modifiers or len(mesh.vertices)!=raw.nv or len(mesh.loops)!=raw.ni or len(mesh.polygons)!=raw.ni//3:
        raise ValueError(obj.name+': topology changes/modifiers are not supported')
    loop_ids = np.empty(raw.ni,dtype=np.int32)
    mesh.loops.foreach_get('vertex_index',loop_ids)
    if not np.array_equal(loop_ids.reshape(-1,3),raw.faces):
        raise ValueError(obj.name+': face connectivity/order changed')
    coords = np.empty((raw.nv,3),dtype=np.float32)
    mesh.vertices.foreach_get('co',coords.ravel())
    coords = coords[:,[0,2,1]]/1000
    attrs = {}
    changed = not np.allclose(coords,raw.positions,rtol=1e-6,atol=1e-9)
    if not changed and mesh.get('IB_normals_baseline') and normals_signature(mesh) != mesh['IB_normals_baseline']:
        raise ValueError(obj.name+': custom-normal-only edits cannot be written back')
    old_colors = raw.attribute(5)
    colors = mesh.color_attributes.get('Game vertex color')
    if old_colors is not None and raw.types[5]==7:
        if colors is None or colors.domain!='POINT' or len(mesh.color_attributes)!=1:
            raise ValueError(obj.name+': vertex color layer changed')
        values = np.empty((raw.nv,4),dtype=np.float32)
        colors.data.foreach_get('color_srgb',values.ravel())
        if not np.array_equal(np.rint(values*255).astype(np.uint8),old_colors.astype(np.uint8)):
            raise ValueError(obj.name+': vertex color edits cannot be written back')
    elif len(mesh.color_attributes):
        raise ValueError(obj.name+': added vertex colors cannot be written back')
    uv0 = None
    expected_layers = []
    for slot in range(8,16):
        old = raw.attribute(slot)
        if old is None or old.shape[1]!=2:
            continue
        name = 'UV'+str(slot-8)
        expected_layers.append(name)
        layer = mesh.uv_layers.get(name)
        if layer is None:
            raise ValueError(obj.name+': missing UV layer '+name)
        loops = np.empty((raw.ni,2),dtype=np.float32)
        layer.data.foreach_get('uv',loops.ravel())
        loops[:,1] = 1-loops[:,1]
        values = old.copy()
        values[loop_ids] = loops
        if not np.allclose(values[loop_ids],loops,rtol=1e-6,atol=1e-6):
            raise ValueError(obj.name+': new UV seam requires vertex splitting (unsupported)')
        attrs[slot] = values
        changed |= not np.allclose(values,old,rtol=1e-6,atol=1e-7)
        if slot==8:
            uv0 = values
    if set(layer.name for layer in mesh.uv_layers)!=set(expected_layers):
        raise ValueError(obj.name+': adding UV layers is unsupported')
    if changed:
        triangles = coords[raw.faces]
        edges1, edges2 = triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0]
        normal = np.zeros_like(coords)
        face_normal = -np.cross(edges1,edges2)
        for col in range(3):
            np.add.at(normal,raw.faces[:,col],face_normal)
        lengths = np.linalg.norm(normal,axis=1)
        normal /= np.maximum(lengths[:,None],1e-20)
        original = raw.attribute(3)
        if original is not None:
            normal[lengths<1e-15] = original[lengths<1e-15,:3]
            attrs[3] = original.copy()
            attrs[3][:,:3] = normal
        if uv0 is not None and raw.attribute(6) is not None and raw.attribute(7) is not None:
            duv = uv0[raw.faces]
            a,b = duv[:,1]-duv[:,0],duv[:,2]-duv[:,0]
            det = a[:,0]*b[:,1]-a[:,1]*b[:,0]
            inv = np.divide(1,det,out=np.zeros_like(det),where=np.abs(det)>1e-15)
            for slot, face_vec in ((6,(edges1*b[:,1,None]-edges2*a[:,1,None])*inv[:,None]),
                                   (7,(edges2*a[:,0,None]-edges1*b[:,0,None])*inv[:,None])):
                values = np.zeros_like(coords)
                for col in range(3):
                    np.add.at(values,raw.faces[:,col],face_vec)
                values -= normal*np.sum(values*normal,axis=1)[:,None]
                norms = np.linalg.norm(values,axis=1)
                values /= np.maximum(norms[:,None],1e-20)
                old = raw.attribute(slot)
                values[norms<1e-15] = old[norms<1e-15,:3]
                attrs[slot] = old.copy()
                attrs[slot][:,:3] = values
    return coords, attrs


def build_mod(job):
    bpy.ops.wm.open_mainfile(filepath=job['blend'], load_ui=False, use_scripts=False)
    text = bpy.data.texts.get('IB_ACTOR_MANIFEST.json')
    if text is None:
        raise ValueError('This .blend was not exported by Actor Workbench')
    project = json.loads(text.as_string())
    if project.get('version') != 1:
        raise ValueError('Unsupported project manifest')
    game = Path(job['game'])
    originals = {}
    for source, expected in project['sources'].items():
        data = inside(game,source).read_bytes()
        if digest(data) != expected:
            raise ValueError('Game source differs from export; re-export first: '+source)
        originals[source] = data
    replacement_objects(project)
    objects = {}
    for obj in bpy.context.scene.objects:
        ident = obj.get('IB_id')
        if ident is None or ident in objects:
            raise ValueError('Added/duplicated objects are unsupported: '+obj.name)
        objects[ident] = obj
    if set(objects) != {n['id'] for n in project['nodes']}:
        raise ValueError('An exported object was removed')
    proposals, socket_edits, trees, shared_xml = {}, {}, {}, {}

    def propose(source, data):
        if source in proposals and proposals[source] != data:
            raise ValueError('Conflicting edits to instances sharing '+source)
        proposals[source] = data

    def xml_node(origin):
        source = origin['source']
        if source not in trees:
            trees[source] = xml_read(inside(game,source))
        node = trees[source]
        for i in origin['address']:
            node = node[i]
        return node

    def set_vector(node, tag, values, keys):
        child = node.find(tag)
        if child is None:
            child = ET.SubElement(node,tag)
        for key,value in zip(keys,values):
            actual_key = next((k for k in child.attrib if k.lower()==key.lower()),key)
            child.set(actual_key,format(float(value),'.9g'))

    def set_text(node,tag,value):
        child = node.find(tag)
        if child is None:
            child = ET.SubElement(node,tag)
        child.text = format(float(value),'.9g')

    for item in project['nodes']:
        obj = objects[item['id']]
        if (obj.parent.get('IB_id') if obj.parent else None) != item['parent'] or obj.constraints or obj.animation_data:
            raise ValueError(obj.name+': hierarchy/constraints/animation changes are unsupported')
        baseline = item['baseline']
        if 'origin' in item:
            key = (item['origin']['source'],tuple(item['origin']['address']))
            signature = list(obj.location)+list(obj.rotation_quaternion)+list(obj.scale)
            if item['kind']=='light':
                signature += list(obj.data.color)+[obj.data.energy]
                if obj.data.type=='SPOT':
                    signature += [obj.data.spot_size,obj.data.spot_blend]
            if key in shared_xml and not close(shared_xml[key],signature):
                raise ValueError('Conflicting XML edits to repeated module; edit all instances consistently: '+obj.name)
            shared_xml[key] = signature
        transformed = not (close(obj.location,baseline['position']) and close(obj.rotation_quaternion,baseline['quaternion']) and close(obj.scale,baseline['scale']))
        if obj.rotation_mode != 'QUATERNION':
            raise ValueError(obj.name+': keep Quaternion rotation mode')
        if transformed and not np.isfinite(np.array(list(obj.location)+list(obj.rotation_quaternion)+list(obj.scale))).all():
            raise ValueError('Non-finite transform')
        if item['kind']=='mesh':
            if transformed:
                raise ValueError(obj.name+': edit mesh vertices or the parent assembly Empty, not the mesh object transform')
            raw = Mesh(originals[item['mesh']])
            expected = project['meshes'][item['mesh']]['materials']
            if [m.get('IB_material') if m else None for m in obj.data.materials] != expected:
                raise ValueError(obj.name+': material slots changed')
            same_material_faces = True
            if expected:
                ids = np.empty(len(obj.data.polygons),dtype=np.int32)
                obj.data.polygons.foreach_get('material_index',ids)
                expected_ids = np.zeros(raw.ni//3,dtype=np.int32)
                for i,g in enumerate(raw.groups):
                    expected_ids[g['first']//3:(g['first']+g['count'])//3] = i
                same_material_faces = np.array_equal(ids,expected_ids)
            try:
                if not same_material_faces or obj.data.get('IB_source') != item['mesh']:
                    raise ValueError('Replacement topology/material assignments')
                coords, attrs = vertex_edits(obj,raw)
                data = raw.patch(coords,attrs)
            except ValueError:
                data = rebuild_mesh(obj,raw)
            propose(item['mesh'],data)
        elif item['kind']=='socket':
            pos, q, scale = object_values(obj,item)
            if not close(scale,[1,1,1]):
                raise ValueError('Socket scaling unsupported')
            values = [pos[0]/1000,pos[2]/1000,pos[1]/1000,-q[1],-q[3],-q[2],q[0]]
            key = (item['mesh'],item['socket'])
            if key in socket_edits and not close(socket_edits[key],values):
                raise ValueError('Conflicting shared socket edits: '+item['socket'])
            socket_edits[key] = values
        elif transformed:
            if 'origin' not in item:
                raise ValueError(obj.name+': generated effect/collision offsets cannot be written back')
            node = xml_node(item['origin'])
            pos,q,scale = object_values(obj,item)
            pos = [v/1000 for v in pos]
            quat = [-q[1],-q[2],-q[3],q[0]]
            for tag, values, keys in (('position',pos,'xyz'),('rotation',quat,'xyzw'),('scale',scale,'xyz')):
                child = node.find(tag)
                if child is None or child.get('Type','').lower() != '3dsmax':
                    values = [values[0],values[2],values[1]]+values[3:]
                set_vector(node,tag,values,keys)
        if item['kind']=='light':
            old = item['light_baseline']
            data = obj.data
            if data.type != old['type']:
                raise ValueError('Changing light types unsupported')
            changed = not(close(data.color,old['color']) and close(data.energy,old['energy']))
            changed |= data.type=='SPOT' and not(close(data.spot_size,old['cone']) and close(data.spot_blend,old['blend']))
            if changed:
                if 'origin' not in item:
                    raise ValueError('Edit thruster settings in game XML; generated light edits cannot be written back')
                node = xml_node(item['origin'])
                set_vector(node,'Color',list(data.color),'XYZ')
                set_text(node,'Lumens',data.energy*683)
                if data.type=='SPOT':
                    set_text(node,'Outercone',math.degrees(data.spot_size))
                    set_text(node,'Innercone',math.degrees(data.spot_size)*(1-data.spot_blend))
    for (ref,name),values in socket_edits.items():
        base = proposals.get(ref,originals[ref])
        proposals[ref] = Mesh(base).patch(sockets={name:values})
    for mat in bpy.data.materials:
        key = mat.get('IB_material')
        if key not in project['materials']:
            continue
        item = project['materials'][key]
        if not item.get('source'):
            continue
        data = bytearray(originals[item['source']])
        for name,param in item['editable'].items():
            if param['kind']=='texture':
                continue
            value = mat.get('IB_param_'+name)
            if value is None:
                raise ValueError('Missing material property '+name)
            values = [float(value)] if param['kind']=='scalar' else list(value)
            if not np.isfinite(values).all():
                raise ValueError('Non-finite material parameter')
            struct.pack_into(param['fmt'],data,param['offset'],*values)
        propose(item['source'],bytes(data))
    texture_edits(project, originals, propose, graph_signature)
    changed_render = [n for n in project['nodes'] if n.get('role') == 'Render' and proposals.get(n['mesh'],originals[n['mesh']]) != originals[n['mesh']]]
    if changed_render:
        unchanged = [n['name'] for n in project['nodes'] if n.get('role') in ('LOD','Collision') and proposals.get(n['mesh'],originals[n['mesh']]) == originals[n['mesh']]]
        if unchanged:
            project['warnings'].append('Render geometry changed but these LOD/collision objects are unchanged (old silhouettes/collisions remain): '+', '.join(unchanged))
        actor = project['actor']
        root = trees.get(actor)
        if root is None:
            root = xml_read(inside(game,actor))
        box = root.find('./Meta/WorldBoxSize')
        if box is not None:
            # Expand the actor's existing origin-centered broad-phase box, never
            # shrink away intentional margins around gameplay attachments.
            required = np.zeros(3)
            for node in project['nodes']:
                if node.get('role') != 'Render':
                    continue
                mesh = Mesh(proposals.get(node['mesh'], originals[node['mesh']]))
                low, high = mesh.positions.min(axis=0), mesh.positions.max(axis=0)
                matrix = objects[node['id']].matrix_world
                for x in (low[0], high[0]):
                    for y in (low[1], high[1]):
                        for z in (low[2], high[2]):
                            world = matrix @ Vector((x*1000,z*1000,y*1000))
                            required = np.maximum(required,np.abs([world.x,world.z,world.y])*2/1000)
            for axis,key in enumerate('XYZ'):
                if required[axis] > float(box.get(key,'0'))*(1+1e-6):
                    box.set(key,format(required[axis],'.9g'))
                    trees[actor] = root
        project['warnings'].append('Mesh bounds rebuilt; existing actor WorldBoxSize expanded if needed. Gameplay settings, sockets and effect placements are not automatically redesigned for the new shape.')
    if any(ref.endswith('.txb') and data != originals[ref] for ref,data in proposals.items()):
        project['warnings'].append('Edited textures use uncompressed RGBA8 mip chains and can use more disk/VRAM. Shared textures affect every actor/material referencing them.')
    for source,root in trees.items():
        propose(source,ET.tostring(root,encoding='utf-8',xml_declaration=True))
    output = Path(job['output'])
    if output.exists():
        raise ValueError('Choose a new mod output directory')
    output.mkdir(parents=True)
    files = []
    for source,data in sorted(proposals.items()):
        if data == originals[source]:
            continue
        atomic_write(inside(output/'payload',source),data)
        files.append(dict(path=source,before=digest(originals[source]),after=digest(data),bytes=len(data)))
    report = dict(version=1,actor=project['actor'],files=files,warnings=project['warnings'],
                  scope='Static mesh replacement/topology/UVs, texture images, socket and XML transforms/lights, existing material scalar/vector parameters')
    atomic_write(output/'mod.json',json.dumps(report,indent=2).encode())
    print('MOD STAGED',len(files),'changed files;',output,flush=True)
    for warning in project['warnings']:
        print('Warning:',warning,flush=True)


def main():
    job = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text('utf8'))
    try:
        if job['action'] in ('inspect-custom','convert-custom','prepare-custom'):
            from ibworkbench.blender_import import inspect_custom, convert_custom
            (inspect_custom if job['action']=='inspect-custom' else convert_custom)(job)
        elif job['action'] in ('new-template','new-actor'):
            from ibworkbench.blender_new_actor import dummy_template, build_new_actor
            (dummy_template if job['action']=='new-template' else build_new_actor)(job)
        else:
            (export if job['action']=='export' else build_mod)(job)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == '__main__':
    main()
