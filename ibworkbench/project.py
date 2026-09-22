"""Resolve actor hierarchies into a Blender-independent manifest."""
from pathlib import Path
import json
import copy
import xml.etree.ElementTree as ET
from .formats import Assets, Mesh, digest, xml_read, material_instance, material_defaults, texture_png, asset_hash


def vector(node, default, keys='xyz'):
    attr = {k.lower(): v for k, v in node.attrib.items()} if node is not None else {}
    return [float(attr.get(k, v)) for k, v in zip(keys, default)]


def transform(node):
    p, q, s = node.find('position'), node.find('rotation'), node.find('scale')
    pos = vector(p, (0, 0, 0))
    quat = vector(q, (0, 0, 0, 1), 'xyzw')
    scale = vector(s, (1, 1, 1))
    # Reflection x,z,y converts engine Y-up to Blender Z-up. Quaternion
    # vector parts change sign under reflection (axial, not polar vectors).
    if p is None or p.get('Type', '').lower() != '3dsmax':
        pos = [pos[0], pos[2], pos[1]]
    if q is None or q.get('Type', '').lower() != '3dsmax':
        quat = [quat[0], quat[2], quat[1], quat[3]]
    if s is None or s.get('Type', '').lower() != '3dsmax':
        scale = [scale[0], scale[2], scale[1]]
    return dict(position=[v*1000 for v in pos], quaternion=[quat[3], -quat[0], -quat[1], -quat[2]], scale=scale)


def catalog(assets):
    rows = []
    for path in sorted((assets.root/'Dev/Config').rglob('*.xml')):
        try:
            root = xml_read(path)
            if not any(n.tag in ('Object', 'Link') for n in root.iter()):
                continue
            kind = root.findtext('./Meta/ActorType') or 'Module / component'
            rows.append(dict(name=path.stem, kind=kind, path=assets.relative(path)))
        except (ValueError, ET.ParseError):
            continue
    return rows


class Project:
    def __init__(self, assets, cache, log=print):
        self.assets, self.cache, self.log = assets, Path(cache), log
        self.cache.mkdir(parents=True, exist_ok=True)
        self.result = dict(version=1, nodes=[], meshes={}, materials={}, textures={}, sources={}, warnings=[])
        self.parsed = {}
        self.mesh_parsed = {}
        self.skin = None

    def texture(self, key):
        tid = f'{key:08x}'
        if tid not in self.result['textures']:
            tex = self.assets.resolve(key, '.txb')
            target = self.cache / (tid+'.png')
            info = texture_png(tex,target)
            info.update(source=self.source(tex),png=str(target.resolve()))
            self.result['textures'][tid] = info
        return tid

    def skin_mesh(self, ref):
        if not self.skin:
            return
        item = self.result['meshes'][ref]
        if item.get('skin_applied'):
            return
        item['skin_applied'] = True
        item['original_materials'] = list(item['materials'])
        for slot, name in self.skin['materials'].items():
            if slot < len(item['materials']):
                item['materials'][slot] = self.material(asset_hash(name))
        if self.skin.get('color_map'):
            tid = self.texture(asset_hash(self.skin['color_map']))
            # ColorMap is a runtime hull binding, not a replacement texture in
            # the original material instance. Keep it preview-only for mod export.
            for slot in self.skin['paint_slots']:
                if slot >= len(item['materials']):
                    continue
                old = item['materials'][slot]
                key = old+'-skin-'+tid
                if key not in self.result['materials']:
                    mat = copy.deepcopy(self.result['materials'][old])
                    mat.update(id=key, preview_skin=self.skin['name'])
                    mat['params']['IB_RuntimeColorMap'] = dict(kind='texture',value=int(tid,16),texture=tid)
                    self.result['materials'][key] = mat
                item['materials'][slot] = key

    def warning(self, message):
        if message not in self.result['warnings']:
            self.result['warnings'].append(message)
            self.log('Warning: '+message)

    def source(self, path):
        relative = self.assets.relative(path)
        if relative not in self.result['sources']:
            self.result['sources'][relative] = digest(Path(path).read_bytes())
        return relative

    def material(self, key):
        ident = f'{key:08x}'
        if ident in self.result['materials']:
            return ident
        item = dict(id=ident, params={}, editable={})
        self.result['materials'][ident] = item
        try:
            path = self.assets.resolve(key, '.cmti')
            item['source'] = self.source(path)
            parent, params = material_instance(path.read_bytes())
            item['parent'] = f'{parent:08x}'
            item['editable'] = params
            try:
                cmat = self.assets.resolve(parent, '.cmat')
                item['shader_source'] = self.source(cmat)
                item['params'] = material_defaults(cmat.read_bytes())
            except ValueError as e:
                self.warning(str(e))
            item['params'].update(params)
            for name, param in item['params'].items():
                if param['kind'] != 'texture':
                    continue
                tid = f'{param["value"]:08x}'
                param['texture'] = tid
                if tid not in self.result['textures']:
                    self.result['textures'][tid] = {}
                    try:
                        tex = self.assets.resolve(param['value'], '.txb')
                        target = self.cache / (tid+'.png')
                        info = texture_png(tex, target)
                        info.update(source=self.source(tex), png=str(target.resolve()))
                        self.result['textures'][tid] = info
                    except (ValueError, OSError, NotImplementedError) as e:
                        self.warning(f'Texture {tid} ({name}): {e}')
        except (ValueError, OSError) as e:
            self.warning(f'Material {ident}: {e}')
        return ident

    def mesh(self, path, render=True):
        relative = self.assets.relative(path)
        if relative not in self.result['meshes']:
            self.log('Reading '+relative)
            mesh = Mesh(path.read_bytes())
            self.mesh_parsed[relative] = mesh
            self.result['meshes'][relative] = dict(source=self.source(path), vertices=mesh.nv,
                 triangles=mesh.ni//3, index_width=mesh.width, materials=[], sockets=mesh.sockets)
        item = self.result['meshes'][relative]
        if render and not item['materials']:
            item['materials'] = [self.material(g['material']) for g in self.mesh_parsed[relative].groups]
        return relative

    def add(self, name, parent, kind='empty', **kwargs):
        ident = str(len(self.result['nodes']))
        item = dict(id=ident, name=name, parent=parent, kind=kind,
                    position=[0,0,0], quaternion=[1,0,0,0], scale=[1,1,1])
        item.update(kwargs)
        self.result['nodes'].append(item)
        return ident

    def build(self, reference):
        path = self.assets.path(reference)
        self.result['actor'] = self.assets.relative(path)
        self.result['name'] = path.stem
        root = xml_read(path)
        selected = root.findtext('./CHullComponent/DefaultSkins/Skin[@TeamID="0"]')
        for skin in root.findall('./CHullComponent/Skin'):
            if skin.findtext('Name') == selected:
                self.skin = dict(name=selected,team=0,color_map=skin.findtext('ColorMap'),
                    materials={int(n.get('ID')):n.text.strip() for n in skin.findall('MeshInstance')},
                    paint_slots=[int(n.get('ID')) for n in root.findall('./CClientHullComponent/Paint/MeshInstance')])
                self.result['skin'] = self.skin
                self.log('Applying default Team 0 skin: '+selected)
        self.file(path, None, ())
        if not any(n['kind'] == 'mesh' and n['role'] == 'Render' for n in self.result['nodes']):
            raise ValueError('No supported render meshes resolved for this actor')
        self.warning('Blender materials are a preview approximation of compiled game shaders; original parameters and texture associations are retained.')
        self.warning('Particle effects are socket-positioned markers, not a simulation of the game particle renderer. Dynamic weapon/loadout attachments are not expanded.')
        self.result['counts'] = {role: sum(n.get('role') == role and n['kind'] == 'mesh' for n in self.result['nodes']) for role in ('Render','Collision','LOD','Cockpit')}
        return self.result

    def file(self, path, parent, stack, lights=True):
        relative = self.source(path)
        if relative in stack or len(stack) >= 48:
            raise ValueError('Cyclic/deep actor link: '+relative)
        if relative not in self.parsed:
            self.parsed[relative] = xml_read(path)
        self.walk(self.parsed[relative], parent, relative, [], stack+(relative,), lights=lights)

    def walk(self, node, parent, source, address, stack, role='Render', sockets=None, lights=True):
        tag = node.tag
        if not isinstance(tag, str):
            return
        origin = dict(source=source, address=address)
        if tag in ('CServerNodeComponent', 'CServerHullComponent') or (tag == 'Condition' and node.get('Target','').lower() == 'server'):
            return
        if tag == 'CClientInternalCockpitComponent':
            role = 'Cockpit'
        if tag == 'Link':
            parent = self.add(Path(node.get('Target','Link')).stem, parent, origin=origin, **transform(node))
            self.file(self.assets.path(node.attrib['Target']), parent, stack, lights=lights and node.get('Lights','true').lower() != 'false')
            return
        if tag in ('Object', 'TransformNode'):
            parent = self.add(node.get('Mesh',tag).rsplit('/',1)[-1], parent, origin=origin, **transform(node))
            if tag == 'Object' and node.get('Mesh'):
                path = self.assets.resolve(node.attrib['Mesh'], '.insm')
                ref = self.mesh(path)
                skin_override = node.find('Material') is not None and node.find('Material').get('Override','').lower()=='true' and role=='Render'
                if skin_override:
                    self.skin_mesh(ref)
                render_scale = vector(node.find('Scale'), (1,1,1))
                render_scale = [render_scale[0],render_scale[2],render_scale[1]]
                self.add('Render: '+node.attrib['Mesh'].rsplit('/',1)[-1], parent, 'mesh', mesh=ref, role=role, scale=render_scale)
                sockets = {}
                for socket in self.result['meshes'][ref]['sockets']:
                    p, q = socket['position'], socket['quaternion']
                    sid = self.add(socket['name'], parent, 'socket', mesh=ref, socket=socket['name'],
                         position=[p[0]*1000,p[2]*1000,p[1]*1000], quaternion=[q[3],-q[0],-q[2],-q[1]])
                    sockets[socket['name']] = sid
                for lod in node.findall('LOD'):
                    if not lod.get('Mesh'):
                        continue
                    lref = self.mesh(self.assets.resolve(lod.attrib['Mesh'], '.insm'))
                    if skin_override:
                        self.skin_mesh(lref)
                    self.add(lod.attrib['Mesh'].rsplit('/',1)[-1], parent, 'mesh', mesh=lref, role='LOD', level=lod.get('Level','1'),scale=render_scale)
                if node.find('Material') is not None:
                    if skin_override and self.skin:
                        self.warning(f'{source}: applied default Team 0 skin {self.skin["name"]}; shader-specific paint masks/tints remain approximate.')
                    else:
                        self.warning(f'{source}: runtime Material override/paint is retained as XML metadata, not reproduced.')
        elif tag == 'Socket':
            if not node.get('Name'):
                # Gameplay hardpoint references are text values, not scene nodes.
                return
            name = node.get('Name', '')
            if name not in (sockets or {}):
                self.warning(f'{source}: missing socket {name}; attachment omitted instead of placed at origin')
                return
            parent = sockets[name]
            offset = vector(node.find('Offset'), (0,0,0))
            parent = self.add('Offset: '+name, parent, position=[offset[0]*1000,offset[2]*1000,offset[1]*1000])
        elif tag == 'CollisionFile':
            ref = self.mesh(self.assets.path(node.text or ''), render=False)
            self.add('Collision: '+Path(ref).stem, parent, 'mesh', mesh=ref, role='Collision')
            return
        elif tag in ('PhysicsBody','HitMesh','CockpitBody'):
            s = float(node.findtext('CollisionScale', '1'))
            parent = self.add(tag, parent, scale=[s]*3)
        elif tag == 'Light':
            if lights:
                self.add(node.findtext('Name',node.get('Type','Light')), parent, 'light', origin=origin,
                         color=vector(node.find('Color'), (1,1,1)), lumens=float(node.findtext('Lumens','1000')),
                         light_type=node.get('Type','PointLight'), cone=float(node.findtext('Outercone','45')),
                         inner=float(node.findtext('Innercone','30')), raw_xml=ET.tostring(node,encoding='unicode'), **transform(node))
            return
        elif tag == 'ThrusterModel':
            target = node.get('ConfigFile')
            if target:
                config = self.assets.path(target)
                self.source(config)
                root = xml_read(config)
                groups = {g.get('ID'): g for g in root.findall('Group')}
                for thruster in root.findall('Thruster'):
                    name = thruster.get('Name')
                    group = groups.get(thruster.get('GroupID'))
                    if name not in (sockets or {}) or group is None:
                        self.warning(f'{source}: unresolved thruster {name}')
                        continue
                    for fx in group:
                        if fx.tag not in ('Light','Particles'):
                            continue
                        offset = float(fx.get('Offset','0')) * 1000
                        if fx.tag == 'Light' and lights:
                            self.add('Thruster light: '+name, sockets[name], 'light', position=[0,offset,0],
                                     light_type='PointLight', color=vector(fx.find('Color'),(1,1,1)),
                                     lumens=float(fx.get('Intensity','1000')), cone=45, inner=30,
                                     raw_xml=ET.tostring(fx,encoding='unicode'))
                        elif fx.tag == 'Particles':
                            self.add('Particles: '+name, sockets[name], 'effect', position=[0,offset,0],
                                     raw_xml=ET.tostring(fx,encoding='unicode'))
            return
        elif tag in ('ParticleEffect','Particles'):
            self.add(node.get('Name',tag), parent, 'effect', raw_xml=ET.tostring(node,encoding='unicode'), **transform(node))
            return
        for index, child in enumerate(node):
            self.walk(child, parent, source, address+[index], stack, role, sockets, lights)


def prepare(game, actor, cache, log=print):
    return Project(Assets(game), cache, log).build(actor)
