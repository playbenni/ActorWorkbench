"""Stock attachment presets and independent configurations for custom actors."""
import copy
import csv
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
from .formats import Mesh, digest, inside, xml_read

SHIPS=('Interceptor','Bomber','Corvette','Hauler','Destroyer','Cruiser','Carrier')
COCKPIT_CAMERA='camera:Cockpit_Camera_Position'
CATEGORIES={'Electronics':'Electronics','Propulsion':'Propulsion','Reactor':'Reactor',
            'Shields':'Shield','Storage':'Storage','Structural':'Structure','WeaponsMod':'Weapon upgrade'}
THRUSTER_NAMES={
    ('Cruiser','0'):'Large main thruster',('Cruiser','1'):'Medium main / retro thruster',
    ('Cruiser','2'):'Small main thruster',('Cruiser','3'):'Manoeuvring jet',
    ('Carrier','0'):'Pod / retro thruster',('Carrier','1'):'Manoeuvring jet',('Carrier','2'):'Large main thruster',
    ('Destroyer','0'):'Small retro thruster',('Destroyer','1'):'Manoeuvring jet',('Destroyer','2'):'Large main / retro thruster',
}


def config_path(game,ref):
    ref=ref.lstrip('$').replace('\\','/')
    if ref.lower().startswith('config/'):ref='Dev/'+ref
    return inside(game,ref)


def readable(value):
    return re.sub(r'(?<=[a-z])(?=[A-Z0-9])',' ',value).replace('_',' ')


def socket_label(name):
    text=name.removeprefix('s_')
    for a,b in (('mjet','manoeuvring jet'),('main','main thruster'),('retro','retro thruster'),
                ('fwd','front'),('aft','rear'),('bot','bottom'),('mod','module')):
        text=re.sub(r'\b'+a+r'\b',b,text.replace('_',' '))
    return text[:1].upper()+text[1:]+' ['+name+']'


def new_socket_name(object_name):
    slug=re.sub('[^A-Za-z0-9_]+','_',object_name).strip('_')[:32] or 'attachment'
    return 's_aw_'+slug+'_'+digest(object_name.encode('utf8'))[:8]


def socket_catalog(game):
    presets=[];sources={};slot_types={};strings={}
    try:
        with config_path(game,'Dev/Localization/en/Strings.csv').open(encoding='utf-8-sig',newline='') as file:
            strings={row[0]:row[1] for row in csv.reader(file) if len(row)>=2}
    except (OSError,UnicodeError):pass
    def read(ref):
        path=config_path(game,ref);sources[path.relative_to(game).as_posix()]=digest(path.read_bytes())
        return xml_read(path)
    for ship in SHIPS:
        path=config_path(game,'$Config/Ships/'+ship+'.xml')
        if not path.exists():continue
        actor=read('$Config/Ships/'+ship+'.xml')
        model=actor.find('./CClientNodeComponent/Object/ThrusterModel')
        if model is not None:
            thrust=read(model.get('ConfigFile'))
            for group in thrust.findall('Group'):
                names=[t.get('Name','') for t in thrust.findall('Thruster') if t.get('GroupID')==group.get('ID')]
                particles=group.find('Particles')
                if particles is None:continue
                description=THRUSTER_NAMES.get((ship,group.get('ID')))
                if not description:
                    description='Manoeuvring jet' if 'Mjet' in particles.get('Name','') else ('Retro thruster' if names and all('retro' in n for n in names) else 'Main thruster')
                ident='thruster:'+ship+':'+group.get('ID')
                size=particles.get('SizeScale','1')
                presets.append(dict(id=ident,kind='thruster',label=ship+' · '+description+' · size '+size,
                                    description='Stock '+ship+' flame and light settings. Effect: '+particles.get('Name','')+'. The Empty controls position and direction; flight performance remains the actor’s.',
                                    xml=ET.tostring(group,encoding='unicode'),ships=[ship]))
        for socket in actor.findall('./CClientNodeComponent/Object/Socket'):
            if socket.find('Light') is None:continue
            presets.append(dict(id='light:'+ship+':'+socket.get('Name'),kind='light',ships=[ship],
                                label=ship+' · '+readable(socket.get('Name').removeprefix('s_')),
                                description='Stock socket light, including its color, intensity, cone and offset.',xml=ET.tostring(socket,encoding='unicode')))
        layout_ref=actor.findtext('./CHardpointComponent/Layout')
        if layout_ref:
            for slot in read(layout_ref).findall('Socket'):
                category,size=slot.findtext('Category'),slot.findtext('Size')
                if category=='Weapon':category='Weapons'
                if category and size:slot_types.setdefault((category,size.upper()),set()).add(ship)
    weapons=read('$Config/Weapons.xml')
    systems=read('$Config/ShipSystems.xml')
    for (category,size),ships in sorted(slot_types.items()):
        if category in CATEGORIES:
            label=CATEGORIES[category]+' module slot · '+size+' · '+', '.join(sorted(ships))
            presets.append(dict(id='module:'+category+':'+size,kind='module',category=category,size=size,
                                ships=sorted(ships),label=label,description='An empty '+category.lower()+' slot. Compatible stock modules can be fitted through the game’s loadout editor; no module is installed automatically.'))
        elif category=='Weapons':
            for weapon in weapons.findall('Weapon'):
                if size not in (weapon.findtext('Class') or '').upper().split(';'):continue
                allowed={n.get('Class') for n in weapon.findall('Actor')}
                donors=ships & allowed if allowed else ships
                if not donors:continue
                ident=weapon.findtext('ID')
                label=strings.get(weapon.findtext('Name'),readable(ident))
                if ident.startswith('Defense'):label+=' (defence variant)'
                presets.append(dict(id='weapon:'+ident+':'+size,kind='weapon',weapon=ident,category='Weapons',size=size,
                                    ships=sorted(donors),label=size+' · '+label+' · '+', '.join(sorted(donors)),
                                    description='Fitted stock weapon: '+label+'. Mount size: '+size+'. Includes its game model, firing configuration and loadout entry. Uses the selected weapon group.'))
    presets.append(dict(id=COCKPIT_CAMERA,kind='camera',label='Cockpit_Camera_Position',ships=list(SHIPS),
                        description='Assign to one Empty at the pilot’s eye position. Its world position, including import scale, sets the cockpit and internal camera positions. Rotation does not change the viewing direction. Assigning another Empty moves this camera marker.'))
    presets.sort(key=lambda p:(p['kind'],p['label']))
    # Include definitions used by a generated baseline loadout in the version check.
    read('$Config/Ships/Loadouts/DefaultInterceptor.xml')
    fingerprint=digest(json.dumps(sources,sort_keys=True).encode())
    return dict(presets=presets,sha256=fingerprint,sources=sources,
                notes=['Hangar launch bays need carrier gameplay components and are not included in these attachment presets.'])


def preset_errors(assignments,catalog,base_sockets):
    presets={p['id']:p for p in catalog.get('presets',[])};errors=[];seen=set()
    if sum(a.get('socket_preset')==COCKPIT_CAMERA for a in assignments)>1:
        errors.append('Assign Cockpit_Camera_Position to only one Empty.')
    for a in assignments:
        name=a.get('socket');ident=a.get('socket_preset','')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,127}',name):
            errors.append('Invalid socket name: '+str(name));continue
        if name in seen:errors.append('Socket assigned more than once: '+name)
        seen.add(name)
        if ident and ident not in presets:errors.append('Socket type is unavailable: '+str(ident))
        if ident==COCKPIT_CAMERA and name in base_sockets:
            errors.append('Cockpit_Camera_Position needs its own marker, not an inherited attachment target.')
        if name not in base_sockets and not ident:errors.append(name+': choose a socket type for this new attachment.')
        if ident and presets.get(ident,{}).get('kind')=='weapon':
            if type(a.get('socket_group',0)) is not int or not 0<=a.get('socket_group',0)<=9:
                errors.append(name+': weapon group must be between 1 and 10.')
    return errors


def with_sockets(raw,sockets):
    """Rebuild the observed length-prefixed INSM socket table, including additions."""
    end=raw.index_start+raw.ni*raw.width+len(raw.groups)*45
    data=bytearray(raw.data[:end]);struct.pack_into('<I',data,18,len(sockets))
    for name,values in sockets.items():
        encoded=name.encode('utf8')
        if not 0<len(encoded)<4096 or len(values)!=7 or not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid socket: '+name)
        if abs(sum(v*v for v in values[3:])-1)>1e-3:raise ValueError('Socket rotation must be normalized: '+name)
        data+=struct.pack('<I',len(encoded))+encoded+struct.pack('<7f',*values)
    return Mesh(data)


def layout_transform(slot):
    p,q=slot.find('position'),slot.find('rotation')
    def values(node,keys,defaults):
        attrs={k.lower():v for k,v in node.attrib.items()} if node is not None else {}
        return [float(attrs.get(k,d)) for k,d in zip(keys,defaults)]
    pos=values(p,'xyz',[0,0,0]);quat=values(q,'xyzw',[0,0,0,1])
    if p is not None and p.get('Type','').lower()=='3dsmax':pos=[pos[0],pos[2],pos[1]]
    if q is not None and q.get('Type','').lower()=='3dsmax':quat=[quat[0],quat[2],quat[1],quat[3]]
    return pos+quat


def set_layout_transform(slot,values):
    for tag,keys,items in (('position','xyz',values[:3]),('rotation','xyzw',values[3:])):
        for old in slot.findall(tag):slot.remove(old)
        ET.SubElement(slot,tag,**{k:format(float(v),'.9g') for k,v in zip(keys,items)})


def set_cockpit_camera(actor,position):
    if len(position)!=3 or not all(math.isfinite(v) for v in position):
        raise ValueError('Invalid cockpit camera position')
    targets=actor.findall('./CClientCameraViewComponent/Camera[@Type="Internal"]')
    cockpit=actor.find('CClientInternalCockpitComponent')
    if cockpit is not None:targets.append(cockpit)
    if not targets:raise ValueError('Actor has no internal camera configuration')
    for target in targets:
        for old in target.findall('ViewPosition'):target.remove(old)
        ET.SubElement(target,'ViewPosition',**{k:format(float(v),'.9g') for k,v in zip('XYZ',position)})


def build_socket_assets(game,name,actor,sockets,settings,catalog):
    """Create thruster/layout/loadout files and narrowly extend equipment eligibility."""
    for ref,expected in catalog.get('sources',{}).items():
        if digest(config_path(game,ref).read_bytes())!=expected:
            raise ValueError('Game attachment definitions changed during conversion: '+ref)
    errors=preset_errors(settings,catalog,{s for s in sockets if not s.startswith('s_aw_')})
    if errors:raise ValueError('\n'.join(errors))
    presets={p['id']:p for p in catalog['presets']}
    chosen={a['socket']:(a,presets[a['socket_preset']]) for a in settings if a.get('socket_preset')}
    payload={};updates={};notes=[]
    for socket,(_,preset) in list(chosen.items()):
        if preset['kind']=='camera':
            set_cockpit_camera(actor,sockets[socket][:3]);del chosen[socket]
            notes.append('Cockpit/internal camera position set from the Cockpit_Camera_Position Empty; viewing direction is unchanged.')
    if not chosen:return payload,updates,notes
    render=actor.find('./CClientNodeComponent/Object')
    model=render.find('ThrusterModel')
    thrust=xml_read(config_path(game,model.get('ConfigFile')))
    for thruster in list(thrust.findall('Thruster')):
        if thruster.get('Name') in chosen:thrust.remove(thruster)
    for node in list(render.findall('Socket')):
        if node.get('Name') in chosen:render.remove(node)
    group_ids={};next_group=max(int(g.get('ID')) for g in thrust.findall('Group'))+1
    for socket,(assignment,preset) in chosen.items():
        if preset['kind']=='thruster':
            key=preset['id']
            if key not in group_ids:
                group_ids[key]=str(next_group);next_group+=1
                group=ET.fromstring(preset['xml']);group.set('ID',group_ids[key]);thrust.append(group)
            ET.SubElement(thrust,'Thruster',ID='0',Name=socket,GroupID=group_ids[key])
        elif preset['kind']=='light':
            light=ET.fromstring(preset['xml']);light.set('Name',socket);render.append(light)
    for i,t in enumerate(thrust.findall('Thruster')):t.set('ID',str(i))
    thrust_ref='Dev/Config/thrusters/'+name+'Thrusters.xml'
    payload[thrust_ref]=ET.tostring(thrust,encoding='utf8',xml_declaration=True)
    model.set('ConfigFile','$'+thrust_ref)
    hardpoints=actor.find('CHardpointComponent')
    layout=xml_read(config_path(game,hardpoints.findtext('Layout')))
    loadout=xml_read(config_path(game,'$Config/Ships/Loadouts/DefaultInterceptor.xml'))
    for root in (layout,loadout):
        root.find('Actor').text=name;root.find('DisplayName').text=name
    layout.set('Name',name+' layout')
    loadout_name='AW_'+name+'_Default';loadout.find('Name').text=loadout_name
    layout_ref='Dev/Config/Ships/Layouts/'+name+'Layout.xml'
    loadout.find('LayoutFile').text='$Config/Ships/Layouts/'+name+'Layout.xml'
    loadout.find('ShortDescr').text='Custom actor loadout'
    for socket,(assignment,preset) in chosen.items():
        for node in list(layout.findall('Socket')):
            if node.get('Name')==socket:layout.remove(node)
        for mount in list(loadout.findall('Mount')):
            if mount.get('HardpointName')==socket:loadout.remove(mount)
        if preset['kind'] in ('weapon','module'):
            slot=ET.SubElement(layout,'Socket',Name=socket)
            ET.SubElement(slot,'Size').text=preset['size'];ET.SubElement(slot,'Category').text=preset['category']
            if preset['kind']=='weapon':
                ET.SubElement(loadout,'Mount',HardpointName=socket,Weapon=preset['weapon'],GroupID=str(assignment.get('socket_group',0)))
    for slot in layout.findall('Socket'):
        key=slot.get('Name')
        if key not in sockets:sockets[key]=layout_transform(slot)
        set_layout_transform(slot,sockets[key])
    for node in list(hardpoints.findall('Hardpoint')):hardpoints.remove(node)
    for i,slot in enumerate(layout.findall('Socket')):
        hp=ET.SubElement(hardpoints,'Hardpoint',ID=str(i));ET.SubElement(hp,'Socket').text=slot.get('Name')
    hardpoints.find('Layout').text='$Config/Ships/Layouts/'+name+'Layout.xml'
    hardpoints.find('ExclusiveWeapons').text='false'
    server=actor.find('CServerHardpointComponent')
    for node in list(server.findall('Loadout')):server.remove(node)
    ET.SubElement(server,'Loadout',Name=loadout_name,Proba='100')
    payload[layout_ref]=ET.tostring(layout,encoding='utf8',xml_declaration=True)
    payload['Dev/Config/Ships/Loadouts/'+loadout_name+'.xml']=ET.tostring(loadout,encoding='utf8',xml_declaration=True)
    # Stock equipment can whitelist actor classes. Add only this custom actor
    # to selected weapons and systems compatible with its supplied module slots.
    weapons=xml_read(config_path(game,'$Config/Weapons.xml'))
    systems=xml_read(config_path(game,'$Config/ShipSystems.xml'))
    weapon_ids={m.get('Weapon') for m in loadout.findall('Mount') if m.get('Weapon')}
    system_ids={m.get('System') for m in loadout.findall('Mount') if m.get('System')}
    for _,preset in chosen.values():
        if preset['kind']!='module':continue
        for system in systems.findall('ShipSystem'):
            allowed={n.get('Class') for n in system.findall('Actor')}
            if system.get('Category')==preset['category'] and preset['size'] in system.get('Class','').upper().split(';') and (not allowed or allowed & set(preset['ships'])):
                system_ids.add(system.get('Name'))
    for root,tag,key,selected,ref in ((weapons,'Weapon','ID',weapon_ids,'Dev/Config/Weapons.xml'),
                                     (systems,'ShipSystem','Name',system_ids,'Dev/Config/ShipSystems.xml')):
        changed=False
        for item in root.findall(tag):
            ident=item.findtext(key) if tag=='Weapon' else item.get(key)
            if ident not in selected:continue
            allowed={n.get('Class') for n in item.findall('Actor')}
            if allowed and name not in allowed:ET.SubElement(item,'Actor',Class=name);changed=True
        if changed:updates[ref]=root
    notes += ['Named attachment presets create an independent thruster config, hardpoint layout and default loadout.',
              'Module presets create empty compatible slots; equip modules in the game loadout editor. Weapons are fitted by the generated default loadout.',
              'Stock weapon/system actor allowlists are extended only for this custom actor when required; these registry edits are backed up by Install.',
              'Effects and weapons retain stock sizes. Empty scaling does not resize them; Interceptor flight/energy settings still require tuning for large equipment.']
    return payload,updates,notes
