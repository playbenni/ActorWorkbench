"""Serializable custom-file assignments, shared by the UI and Blender worker."""
import math
from pathlib import Path
from .new_actor import actor_name, PROFILE
from .socket_types import preset_errors, COCKPIT_CAMERA

ROLES = {
    'ignore': 'Ignore', 'render': 'Visible mesh (LOD 0)', 'collision': 'Collision / hit mesh',
    **{f'lod{i}': f'LOD {i}' for i in range(1,7)},
    'exterior_cockpit': 'Exterior cockpit', 'interior_cockpit': 'Interior cockpit',
    'cockpit_collision': 'Cockpit collision', 'socket': 'Attachment socket',
}
COLLECTIONS = {'render':'Render', 'collision':'Collision',
               **{f'lod{i}':f'LOD{i}' for i in range(1,7)},
               'exterior_cockpit':'ExteriorCockpit','interior_cockpit':'InteriorCockpit',
               'cockpit_collision':'CockpitCollision'}
VISUAL_ROLES = {'render','exterior_cockpit','interior_cockpit',*(f'lod{i}' for i in range(1,7))}
MODES = {'principled':'Principled + linked textures', 'diffuse':'Diffuse color only'}
RESOLUTIONS = (128,256,512,1024,2048)
FORMATS = ('.blend','.glb','.gltf')


def suggested_role(item):
    if 'Ignored' in item.get('collections',[]):
        return 'ignore'
    if item.get('socket'):
        return 'socket'
    if item['type'] != 'MESH':
        return 'ignore'
    collections = set(item.get('collections',[]))
    for role,collection in COLLECTIONS.items():
        if collection in collections:
            return role
    # Names alone never silently turn an arbitrary object into a collision hull.
    return 'render'


def default_plan(inspection):
    stem=Path(inspection['source']).stem
    name=''.join(c if c.isascii() and (c.isalnum() or c=='_') else '_' for c in stem)
    name=('Custom_'+name if not name or not name[0].isalpha() else name)[:40]
    if len(name)<3 or name.lower()=='interceptor':name='CustomActor'
    return dict(version=1,profile=PROFILE,source=inspection['source'],source_sha256=inspection['source_sha256'],
                name=name,scale=float(inspection.get('suggested_scale',1)),resolution=512,default_sockets=True,
                socket_catalog_sha256=inspection.get('socket_catalog',{}).get('sha256'),
                objects=[dict(name=o['name'],role=suggested_role(o),socket=o.get('socket') or '',
                              socket_preset=o.get('socket_preset',''),socket_group=o.get('socket_group',0)) for o in inspection['objects']],
                materials=[dict(object=o['name'],slot=s['index'],source_material=s['material'],mode='principled',resolution=512)
                           for o in inspection['objects'] if o['type']=='MESH' for s in o['slots']])


def recipe_structure_errors(plan):
    """Reject malformed recipes before either the UI or worker consumes them."""
    if not isinstance(plan,dict):return ['Import recipe must be a JSON object.']
    errors=[]
    for key in ('source','source_sha256','name','profile'):
        if not isinstance(plan.get(key),str):errors.append('Recipe needs a text field: '+key)
    for key in ('scale','resolution'):
        if type(plan.get(key)) not in (int,float):errors.append('Recipe needs a numeric field: '+key)
    if not isinstance(plan.get('default_sockets'),bool):errors.append('Recipe needs a default_sockets checkbox value.')
    for key in ('objects','materials'):
        if not isinstance(plan.get(key),list):errors.append('Recipe needs a list: '+key);continue
        for item in plan[key]:
            fields=('name','role','socket') if key=='objects' else ('object','mode')
            if not isinstance(item,dict) or any(not isinstance(item.get(f),str) for f in fields):
                errors.append('Invalid '+key+' assignment.');break
            if key=='objects' and (not isinstance(item.get('socket_preset',''),str) or type(item.get('socket_group',0)) is not int):
                errors.append('Invalid socket type or weapon group.');break
            if key=='materials' and (type(item.get('slot')) is not int or item['slot']<0 or
                                     'source_material' not in item or
                                     (item['source_material'] is not None and not isinstance(item['source_material'],str)) or
                                     type(item.get('resolution')) is not int):
                errors.append('Invalid material slot, source material or resolution.');break
    return errors


def validate_plan(plan, inspection):
    malformed=recipe_structure_errors(plan)
    if malformed:return malformed,[]
    errors=[];warnings=[]
    if plan.get('version')!=1 or plan.get('profile')!=PROFILE:
        errors.append('Unsupported import recipe/profile.')
    try:actor_name(plan.get('name'))
    except ValueError as e:errors.append(str(e))
    if str(Path(plan.get('source','')).resolve()).lower()!=str(Path(inspection['source']).resolve()).lower():
        errors.append('Recipe belongs to a different source file.')
    if plan.get('source_sha256')!=inspection['source_sha256']:
        errors.append('Source file changed. Inspect it again before converting.')
    scale=plan.get('scale')
    if not isinstance(scale,(int,float)) or not math.isfinite(scale) or not 1e-6<=scale<=1e6:
        errors.append('Scale to meters must be finite and between 0.000001 and 1000000.')
    if plan.get('resolution') not in RESOLUTIONS:errors.append('Choose a supported texture resolution.')
    objects={o['name']:o for o in inspection['objects']}
    materials={m['name']:m for m in inspection['materials']}
    roles={};socket_map={}
    for assignment in plan.get('objects',[]):
        name,role=assignment.get('name'),assignment.get('role')
        if name in roles:errors.append('Duplicate object assignment: '+str(name))
        roles[name]=role
        if name not in objects:errors.append('Object is no longer present: '+str(name));continue
        if role not in ROLES:errors.append('Unknown role: '+str(role));continue
        obj=objects[name]
        if role in COLLECTIONS and obj['type']!='MESH':errors.append(name+': this role requires a mesh.')
        if role in COLLECTIONS and obj.get('faces',0)==0:errors.append(name+': the mesh has no faces.')
        if role in COLLECTIONS and obj.get('geometry_issue'):errors.append(name+': '+obj['geometry_issue'])
        if role=='socket':
            if assignment.get('socket_preset')==COCKPIT_CAMERA and obj['type']!='EMPTY':
                errors.append(name+': Cockpit_Camera_Position must be assigned to an Empty.')
            socket=assignment.get('socket')
            socket_map[socket]=name
    attachments=[a for a in plan['objects'] if a['role']=='socket']
    errors.extend(preset_errors(attachments,inspection.get('socket_catalog',{}),inspection['sockets']))
    if any(a.get('socket_preset') for a in attachments):
        if plan.get('socket_catalog_sha256')!=inspection.get('socket_catalog',{}).get('sha256'):
            errors.append('Game attachment definitions changed. Reinspect the file and reapply the socket types.')
        if any(a.get('socket_preset') and a['socket_preset']!=COCKPIT_CAMERA for a in attachments):
            warnings.append('Attachment presets retain stock equipment sizes. Large weapons need suitable geometry and flight/energy settings.')
    if set(roles)!=set(objects):errors.append('Every source object needs an assignment (use Ignore for unused objects).')
    for role in ('render','collision'):
        if role not in roles.values():errors.append('Assign at least one '+ROLES[role].lower()+'.')
    if 'cockpit_collision' in roles.values() and 'interior_cockpit' not in roles.values():
        errors.append('Cockpit collision requires an interior cockpit mesh.')
    levels=sorted(int(role[3:]) for role in set(roles.values()) if role in {f'lod{i}' for i in range(1,7)})
    if levels and levels!=list(range(1,max(levels)+1)):errors.append('LOD levels must be consecutive, starting with LOD 1.')
    missing=set(inspection['sockets'])-set(socket_map)
    if missing:
        if plan.get('default_sockets'):
            warnings.append(f'{len(missing)} unassigned sockets will use the Interceptor positions; check weapon/thruster placement.')
        else:errors.append('Assign all sockets or enable default socket positions: '+', '.join(sorted(missing)))
    slots={}
    for assignment in plan.get('materials',[]):
        key=(assignment.get('object'),assignment.get('slot'))
        if key in slots:errors.append('Duplicate material slot assignment: '+str(key))
        slots[key]=assignment
    expected_slots={(obj['name'],slot['index']) for obj in objects.values() for slot in obj['slots']}
    if set(slots)!=expected_slots:errors.append('Every mesh slot needs one material assignment, including currently ignored meshes.')
    for name,role in roles.items():
        if role not in VISUAL_ROLES or name not in objects:continue
        for slot in objects[name]['slots']:
            key=(name,slot['index']);assignment=slots.get(key)
            label=f'{name}, slot {slot["index"]+1}'
            if assignment is None:errors.append(label+': select a material.');continue
            mode=assignment.get('mode');source=assignment.get('source_material')
            if mode not in MODES:errors.append(label+': choose a conversion mode.');continue
            if assignment.get('resolution') not in RESOLUTIONS:errors.append(label+': choose a supported texture resolution.')
            if source is not None and source not in materials:errors.append(label+': selected material is missing.');continue
            if mode=='principled':
                if source is None:errors.append(label+': no source material; choose a material or Diffuse color only.')
                elif materials[source].get('issue'):errors.append(label+': '+materials[source]['issue'])
            else:warnings.append(label+': only the selected material’s diffuse color is used; texture/shader links are omitted.')
    if 'interior_cockpit' in roles.values() and 'cockpit_collision' not in roles.values():
        warnings.append('Interior cockpit has no separate cockpit collision mesh.')
    if not levels:warnings.append('No LOD meshes assigned; only the full-detail mesh will be exported.')
    return errors,warnings
