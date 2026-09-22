"""Data-only Interceptor actor creation: independent assets and registry entries."""
from pathlib import Path
import copy
import json
import re
import struct
import xml.etree.ElementTree as ET
import numpy as np
from .formats import Assets, Mesh, asset_hash, digest, inside, xml_read, material_instance
from .mods import atomic_write

PROFILE = 'interceptor-principled-v1'
SHADER = 0xd819ce37
SHADER_SHA = '569f8f6d6a72c34f74f068b4f43e60febd0809ab8705cee5c1dd3109d353712e'
BASE_ACTOR = 'Dev/Config/Ships/Interceptor.xml'
BASE_MESH = 'Ships/SFC-Fighter/SM_SFC_Fighter_exterior_no_cockpit_Lod0'
BASE_COLLISION = 'Dev/Ships/SFC-Fighter/Collision/7d2d7b6d.insm'


def actor_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{2,47}', value):
        raise ValueError('Actor name must be 3–48 letters/digits/underscores, starting with a letter')
    if value.lower() == 'interceptor':
        raise ValueError('Choose a new actor name, not Interceptor')
    return value


def profile_assets(game):
    assets = Assets(game)
    if digest(assets.resolve(SHADER, '.cmat').read_bytes()) != SHADER_SHA:
        raise ValueError('Interceptor shader differs from the verified conversion profile')
    return assets


def material_bytes(parameters):
    data = bytearray(b'mati\x01\x00'+struct.pack('<IH',SHADER,len(parameters)))
    for name,(kind,value) in parameters.items():
        encoded = name.encode('utf8')
        desc,fmt = {'texture':(b'\x03\x00','<I'),'scalar':(b'\x02\x07','<f'),'vector':(b'\x02\x02','<4f')}[kind]
        data += struct.pack('<I',len(encoded))+encoded+desc+b'\x00\x01\x00'
        data += struct.pack(fmt,*(value if kind=='vector' else [value]))
    material_instance(data)
    return bytes(data)


def layout_materials(raw, ids):
    """Clone a known vertex/socket layout with a new material-group list."""
    if not ids:
        raise ValueError('At least one material is required')
    header = bytearray(raw.data[:260])
    struct.pack_into('<I',header,14,len(ids))
    end = raw.index_start+raw.ni*raw.width
    groups = bytearray()
    low,high = raw.positions.min(axis=0),raw.positions.max(axis=0)
    for i,ident in enumerate(ids):
        groups += struct.pack('<B5I6f',1,0 if i==0 else raw.ni,0,raw.ni if i==0 else 0,raw.nv if i==0 else 0,ident,*low,*high)
    return Mesh(bytes(header)+raw.data[260:end]+groups+raw.data[end+len(raw.groups)*45:])


def pack_channels(base, roughness, metallic, emission, normals):
    """Linear Principled samples -> skin SRGB, data UNORM, normal SNORM."""
    base = np.asarray(base,np.float32).copy()
    for values in (base,roughness,metallic,emission,normals):
        if not np.isfinite(values).all():
            raise ValueError('Material baking produced non-finite pixels')
    if base.min() < -1e-5 or base.max() > 1.0001:
        raise ValueError('HDR base colors cannot be represented by the Interceptor shader')
    if emission.min() < -1e-5:
        raise ValueError('Negative emission cannot be represented')
    glow = np.maximum(emission,0)
    peak = glow.max(axis=2)
    lit = peak > 1e-5
    level = np.maximum(base.max(axis=2),.04)
    base[lit] = glow[lit]/peak[lit,None]*level[lit,None]
    ratio = np.where(lit,peak/level,0)
    maximum = float(ratio.max())
    mask = ratio/maximum if maximum else ratio
    skin = np.ones((*base.shape[:2],4),np.float32)
    skin[:,:,:3] = np.where(base <= .0031308,base*12.92,1.055*np.maximum(base,0)**(1/2.4)-.055)
    skin[:,:,3] = np.clip(roughness,0,1)
    data = np.ones_like(skin)
    data[:,:,1] = np.clip(metallic,0,1)
    data[:,:,2] = mask
    normal = np.ones_like(skin)
    normal[:,:,:3] = np.clip(normals,0,1)
    normal[:,:,1] = 1-normal[:,:,1]
    # Quantized signed XY must remain inside the unit disk for shader sqrt.
    xy = np.rint((normal[:,:,:2]*2-1)*127)
    length = np.linalg.norm(xy,axis=2)
    outside = length > 127
    xy[outside] = np.trunc(xy[outside]*(126.9/length[outside,None]))
    normal[:,:,:2] = xy/254+.5
    return skin,data,normal,maximum*10,bool(lit.any())


def register_assets(toc, records):
    result = copy.deepcopy(toc)
    existing = {int(e.get('Name')) & 0xffffffff for e in result.findall('Entry')}
    types = {}
    paths = set()
    for e in result.findall('Entry'):
        for f in e.findall('File'):
            paths.add((f.text or '').replace('\\','/').lower())
            types.setdefault(Path(f.text or '').suffix.lower(),e.get('Type'))
    for logical,ref in records:
        ident = asset_hash(logical)
        if ident in existing or ('$'+ref).lower() in paths:
            raise ValueError('Asset name/hash already registered: '+logical)
        ext = Path(ref).suffix.lower()
        if ext not in types:
            raise ValueError('No known registry type for '+ext)
        e = ET.SubElement(result,'Entry',Name=str(ident if ident < 2**31 else ident-2**32),DebugName=logical,Type=types[ext])
        ET.SubElement(e,'File').text = '$'+ref
        existing.add(ident)
        paths.add(('$'+ref).lower())
    return result


def actor_xml(game, name, render_ref, collision_ref, bounds):
    root = xml_read(inside(game,BASE_ACTOR))
    root.find('./Meta/DisplayName').text = name
    root.find('./Meta/ClassAbbrev').text = name[:8].upper()
    for node in root.findall('./CServerActorComponent/Name'):
        node.text = name
    for tag in ('CClientExternalCockpitComponent','CClientInternalCockpitComponent'):
        for node in root.findall(tag):
            root.remove(node)
    for parent in root.iter():
        for child in list(parent):
            if child.tag in ('Skin','DefaultSkins','Paint'):
                parent.remove(child)
    client = root.find('CClientNodeComponent')
    obj = client.find('Object')
    obj.set('Mesh',render_ref)
    for child in list(obj):
        if child.tag in ('LOD','Material','LODPower'):
            obj.remove(child)
    collision = root.find('./CBodyComponent/HitMesh/CollisionFile')
    collision.text = '$'+collision_ref
    for node in root.findall('./CClientHullComponent/ReentryMesh'):
        root.find('CClientHullComponent').remove(node)
    for node in root.findall('./CHullComponent/MainDeathDebris'):
        root.find('CHullComponent').remove(node)
    # Bounds are origin-centered and converted from Blender meters to game km.
    size = np.maximum(np.max(np.abs(bounds),axis=0)*2/1000,1e-5)[[0,2,1]]
    for path in ('./Meta/WorldBoxSize','./CBodyComponent/PhysicsBody/SidesSize'):
        element = root.find(path)
        for key,value in zip('XYZ',size):
            element.set(key,format(float(value),'.9g'))
    return root


def add_mesh_roles(actor,lods,exterior=None,interior=None,cockpit_collision=None,cockpit_template=None):
    obj=actor.find('./CClientNodeComponent/Object')
    for level,logical in sorted(lods.items()):
        ET.SubElement(obj,'LOD',Level=str(level),Mesh=logical)
    if lods:ET.SubElement(obj,'LODPower').text='4.0'
    if exterior:
        component=ET.SubElement(actor,'CClientExternalCockpitComponent')
        ET.SubElement(component,'Object',Mesh=exterior)
    if interior:
        component=ET.SubElement(actor,'CClientInternalCockpitComponent')
        if cockpit_collision:
            body=ET.SubElement(component,'CockpitBody')
            ET.SubElement(body,'CollisionFile').text='$'+cockpit_collision
        ET.SubElement(component,'Object',Mesh=interior)
        # View/head settings are independent of the original cockpit's material
        # slots. Do not copy its MFD bindings, bobblehead or light/socket links.
        if cockpit_template is not None:
            for tag in ('ViewPosition','Head'):
                setting=cockpit_template.find(tag)
                if setting is not None:component.append(copy.deepcopy(setting))


def stage_package(game, name, output, payload, registrations, actor, warnings, registry_updates=None, registry_sources=None):
    name = actor_name(name)
    output = Path(output)
    if output.exists():
        raise ValueError('Choose a new output directory')
    game = Path(game)
    assets = Assets(game)
    for logical,ref in registrations:
        if any(key[0] == asset_hash(logical) for key in assets.index):
            raise ValueError('Asset ID already exists in Engine or Dev: '+logical)
    toc = register_assets(xml_read(game/'Dev/toc.xml'),registrations)
    actors = xml_read(game/'Dev/Config/ActorsList.xml')
    if any((n.get('ClassName') or '').lower()==name.lower() for n in actors):
        raise ValueError('Actor name already registered: '+name)
    actor_ref = 'Dev/Config/Ships/Custom/'+name+'.xml'
    ET.SubElement(actors,'ActorType',ClassName=name,ConfigFile='$'+actor_ref)
    payload = dict(payload)
    payload[actor_ref] = ET.tostring(actor,encoding='utf-8',xml_declaration=True)
    for ref in payload:
        if inside(game,ref).exists():
            raise ValueError('New asset would overwrite an existing file: '+ref)
    registry_updates=registry_updates or {}
    if not set(registry_updates).issubset({'Dev/Config/Weapons.xml','Dev/Config/ShipSystems.xml'}):
        raise ValueError('Unsupported attachment registry update')
    for ref,expected in (registry_sources or {}).items():
        if ref not in registry_updates or digest(inside(game,ref).read_bytes())!=expected:
            raise ValueError('Equipment registry changed during conversion: '+ref)
    registry = {'Dev/toc.xml':toc,'Dev/Config/ActorsList.xml':actors,**registry_updates}
    payload.update({ref:ET.tostring(tree,encoding='utf-8',xml_declaration=True) for ref,tree in registry.items()})
    files = [dict(path=ref,before=digest(inside(game,ref).read_bytes()) if ref in registry else None,after=digest(data),bytes=len(data)) for ref,data in sorted(payload.items())]
    shader_ref = assets.relative(assets.resolve(SHADER,'.cmat'))
    report = dict(version=2,actor=actor_ref,actor_name=name,profile=PROFILE,files=files,
                  requires=[dict(path=shader_ref,sha256=SHADER_SHA)],warnings=warnings,
                  scope='New actor, independent meshes/materials/textures; additions to asset and actor registries')
    # Publish only a complete staging directory; never write to the game here.
    import tempfile, shutil
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.new-actor-',dir=output.parent))
    try:
        for ref,data in payload.items():
            atomic_write(inside(temporary/'payload',ref),data)
        atomic_write(temporary/'mod.json',json.dumps(report,indent=2).encode())
        if output.exists():
            raise ValueError('Output appeared during staging')
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return report
