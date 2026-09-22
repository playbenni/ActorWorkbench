"""Blender-only extraction of replacement topology and edited texture images."""
import json
import struct
import numpy as np
import bpy
from .texture_writeback import encode_texture
from .formats import digest


def rebuild_mesh(obj, raw):
    if obj.data.shape_keys:
        raise ValueError(obj.name + ': shape keys are not supported')
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=bpy.context.evaluated_depsgraph_get())
    try:
        mesh.calc_loop_triangles()
        if not len(mesh.loop_triangles):
            raise ValueError(obj.name + ': replacement has no faces')
        loops = np.array([t.loops[:] for t in mesh.loop_triangles], dtype=np.int32).ravel()
        ids = np.array([loop.vertex_index for loop in mesh.loops], dtype=np.int32)[loops]
        coords = np.empty((len(mesh.vertices), 3), dtype=np.float32)
        mesh.vertices.foreach_get('co', coords.ravel())
        attrs = {1: coords[ids][:, [0, 2, 1]]/1000}
        normals = np.empty((len(mesh.corner_normals), 3), dtype=np.float32)
        mesh.corner_normals.foreach_get('vector', normals.ravel())
        uv0 = mesh.uv_layers.get('UV0') or mesh.uv_layers.active
        uv_name = uv0.name if uv0 else None
        if any(raw.sizes[s] for s in (6, 7)):
            if uv0 is None:
                raise ValueError(obj.name + ': replacement needs a UV map for game tangents')
            mesh.calc_tangents(uvmap=uv0.name)
        for slot, size in enumerate(raw.sizes):
            if not size or slot == 1:
                continue
            old = raw.attribute(slot)
            if old is None:
                raise ValueError(f'{obj.name}: unsupported channel {slot}')
            values = np.zeros((len(loops), old.shape[1]), dtype=np.float32)
            if slot == 3:
                values[:, :3] = normals[loops][:, [0, 2, 1]]
            elif slot in (6, 7):
                vectors = np.array([getattr(loop, 'tangent' if slot == 6 else 'bitangent')[:] for loop in mesh.loops], dtype=np.float32)
                values[:, :3] = vectors[loops][:, [0, 2, 1]] * (1 if slot == 6 else -1)
            elif slot == 5 and raw.types[slot] == 7:
                color = mesh.color_attributes.get('Game vertex color') or mesh.color_attributes.active_color
                if color:
                    if color.domain not in ('POINT', 'CORNER'):
                        raise ValueError('Unsupported vertex color domain')
                    colors = np.empty((len(color.data), 4), dtype=np.float32)
                    color.data.foreach_get('color_srgb', colors.ravel())
                    values[:] = np.rint(np.clip(colors[ids if color.domain == 'POINT' else loops], 0, 1)*255)
                else:
                    values[:] = 255
            elif 8 <= slot < 16 and old.shape[1] == 2:
                layer = mesh.uv_layers.get('UV'+str(slot-8)) or (mesh.uv_layers.get(uv_name) if uv_name else None)
                if layer is None:
                    raise ValueError(obj.name + ': replacement needs UV coordinates')
                uv = np.empty((len(mesh.loops), 2), dtype=np.float32)
                layer.data.foreach_get('uv', uv.ravel())
                values[:] = uv[loops]
                values[:, 1] = 1-values[:, 1]
            else:
                raise ValueError(f'{obj.name}: unsupported replacement channel {slot}')
            # Preserve constant auxiliary components (e.g. half4 padding).
            if slot in (3, 6, 7) and old.shape[1] > 3:
                if not np.all(old[:, 3:] == old[0, 3:]):
                    raise ValueError(f'{obj.name}: unknown varying auxiliary channel {slot}')
                values[:, 3:] = old[0, 3:]
            attrs[slot] = values
        # Split corners at hard normals, UV seams and vertex colors, then weld
        # only exactly equal complete records. Never weld by position alone.
        slots = sorted(attrs)
        records = np.concatenate([attrs[slot] for slot in slots], axis=1)
        _, unique, inverse = np.unique(records, axis=0, return_index=True, return_inverse=True)
        channels = {slot: values[unique] for slot, values in attrs.items()}
        materials = np.array([t.material_index for t in mesh.loop_triangles], dtype=np.int32)
        return raw.rebuild(channels[1], inverse.reshape(-1, 3), channels, materials)
    finally:
        evaluated.to_mesh_clear()


def replacement_objects(project):
    """An extra object named REPLACE:<exported object name> replaces its data.

    Keep the exported object as a target; preserve its hierarchy and sockets.
    The replacement's world transform is baked into the target's local space.
    """
    originals = {o.name: o for o in bpy.context.scene.objects if o.get('IB_id') is not None}
    replacements = [o for o in bpy.context.scene.objects if o.get('IB_id') is None and o.name.startswith('REPLACE:')]
    used = set()
    for replacement in replacements:
        name = replacement.name[len('REPLACE:'):].strip()
        target = originals.get(name)
        if target is None or target.type != 'MESH' or replacement.type != 'MESH' or name in used:
            raise ValueError('Invalid/duplicate replacement target: ' + replacement.name)
        if replacement.constraints or replacement.animation_data or replacement.data.shape_keys:
            raise ValueError('Replacement constraints, animation and shape keys are unsupported')
        used.add(name)
        evaluated = replacement.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=bpy.context.evaluated_depsgraph_get())
        mesh.transform(target.matrix_world.inverted() @ replacement.matrix_world)
        materials = list(target.data.materials)
        keys = [m.get('IB_material') if m else None for m in materials]
        remap = []
        for material in mesh.materials:
            key = material.get('IB_material') if material else None
            if key not in keys:
                raise ValueError(replacement.name + ': reuse original game materials, or remove all material slots to use slot 0')
            remap.append(keys.index(key))
        for polygon in mesh.polygons:
            polygon.material_index = remap[polygon.material_index] if remap else 0
        mesh.materials.clear()
        for material in materials:
            mesh.materials.append(material)
        target.data = mesh
        target.modifiers.clear()
        # Sockets stay on the original object; the helper is not an added actor.
        bpy.data.objects.remove(replacement, do_unlink=True)


def image_texture(image, original):
    if image.source not in ('FILE', 'GENERATED') or image.type not in ('IMAGE', 'UV_TEST'):
        raise ValueError('Only ordinary 2D replacement images are supported')
    width, height = image.size[:]
    if not width or not height or max(width, height) > 8192:
        raise ValueError('Replacement image is missing or too large')
    pixels = np.empty(width*height*4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)[::-1].copy()
    # Blender byte-backed image.pixels are encoded values; float-backed sRGB
    # images are scene-linear. Encode those explicitly before TXB storage.
    if image.is_float and image.colorspace_settings.name == 'sRGB':
        rgb = pixels[:, :, :3]
        pixels[:, :, :3] = np.where(rgb <= .0031308, rgb*12.92, 1.055*np.maximum(rgb, 0)**(1/2.4)-.055)
    # Signed tangent-space normal textures need a signed GPU resource. Keep
    # their Blender pixels in the usual 0..1 range for Normal Map previews.
    if image.get('IB_export_signed_normal', False):
        if image.colorspace_settings.name != 'Non-Color':
            raise ValueError('Signed normal export requires a Non-Color image')
        template = bytearray(original)
        struct.pack_into('<I', template, 28, 31)  # R8G8B8A8_SNORM
        original = bytes(template)
    return encode_texture(original, pixels)


def texture_edits(project, originals, propose, graph_signature):
    processed = set()
    for material in bpy.data.materials:
        key = material.get('IB_material')
        if key not in project['materials']:
            continue
        baseline = json.loads(material['IB_graph_baseline'])
        current = json.loads(graph_signature(material))
        old_nodes = {node[0]: node for node in baseline[0]}
        params = project['materials'][key]['params']
        for node in current[0]:
            param = params.get(node[0], {})
            tid = param.get('texture')
            if node[1] != 'ShaderNodeTexImage' or tid not in project['textures'] or node[0] not in old_nodes:
                continue
            image = material.node_tree.nodes[node[0]].image
            if image is None:
                raise ValueError(material.name + ': texture image was removed')
            if node[4] != old_nodes[node[0]][4]:
                raise ValueError(material.name + ': retain the original texture node image color space (' + str(old_nodes[node[0]][4]) + ')')
            info = project['textures'][tid]
            replaced = node[3:5] != old_nodes[node[0]][3:5]
            changed = replaced or image.is_dirty or not image.packed_file or digest(image.packed_file.data) != info.get('packed_sha256')
            if changed and (image.as_pointer(), tid) not in processed:
                propose(info['source'], image_texture(image, originals[info['source']]))
                processed.add((image.as_pointer(), tid))
            # Only replacing the image is allowed; links/math/shader settings
            # must still match. Texture names identify original game bindings.
            node[3:5] = old_nodes[node[0]][3:5]
        if current != baseline:
            raise ValueError(material.name + ': shader node/link edits are unsupported; replace images in existing texture nodes')
    # Painted/reloaded original image datablocks can be edited even if unused.
    for image in bpy.data.images:
        tid = image.get('IB_texture')
        if tid not in project['textures'] or (image.as_pointer(), tid) in processed:
            continue
        info = project['textures'][tid]
        if image.is_dirty or not image.packed_file or digest(image.packed_file.data) != info.get('packed_sha256'):
            propose(info['source'], image_texture(image, originals[info['source']]))
