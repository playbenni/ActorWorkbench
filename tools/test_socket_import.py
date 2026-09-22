"""Real Blender/glTF socket conversion and saved-scene replay, without game writes."""
import json
import subprocess
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ibworkbench.runner import inspect_custom_file,convert_custom_file,blender_path,stage_new_actor
from ibworkbench.import_plan import validate_plan,default_plan
from ibworkbench.socket_types import new_socket_name,layout_transform
from ibworkbench.formats import Mesh,digest

base=Path(__file__).resolve().parent.parent
fixture=base/'samples/import-ui-validation';folder=base/'samples/socket-validation';folder.mkdir(exist_ok=True)
game=Path('A:/Steam/steamapps/common/Infinity Battlescape')
before={ref:digest((game/ref).read_bytes()) for ref in ('Dev/toc.xml','Dev/Config/ActorsList.xml','Dev/Config/Weapons.xml','Dev/Config/ShipSystems.xml')}
for extension in sys.argv[1:] or ['blend','glb']:
    scan=inspect_custom_file(game,fixture/('arbitrary.'+extension),blender_path())
    (folder/(extension+'-inspection.json')).write_text(json.dumps(scan,indent=2),encoding='utf8')
    plan=json.loads((fixture/(extension+'-recipe.json')).read_text('utf8'))
    plan.update(name='SocketTypes'+extension.title(),socket_catalog_sha256=scan['socket_catalog']['sha256'])
    choices={'mystery_nozzle':'thruster:Cruiser:0','s_main_top_right':'thruster:Carrier:2',
             'unused_bolt':'weapon:TurretGunMK7:MK7','far_away_shape':'module:Shields:MK6',
             'CanopyShell':'light:Corvette:s_spotlight'}
    for a in plan['objects']:
        if a['name'] in choices:
            a.update(role='socket',socket=a['socket'] or new_socket_name(a['name']),socket_preset=choices[a['name']],socket_group=3)
    for m in plan['materials']:m['resolution']=128
    errors,_=validate_plan(plan,scan);assert not errors,errors
    (folder/(extension+'-recipe.json')).write_text(json.dumps(plan,indent=2),encoding='utf8')
    output=folder/(extension+'-mod');convert_custom_file(game,blender_path(),plan,output)
    report=json.loads((output/'mod.json').read_text('utf8'));payload=output/'payload'
    actor=ET.parse(payload/report['actor']).getroot()
    loadout=ET.parse(payload/('Dev/Config/Ships/Loadouts/AW_'+plan['name']+'_Default.xml')).getroot()
    layout=ET.parse(payload/('Dev/Config/Ships/Layouts/'+plan['name']+'Layout.xml')).getroot()
    thrust=ET.parse(payload/('Dev/Config/thrusters/'+plan['name']+'Thrusters.xml')).getroot()
    body=next(Mesh((payload/e['path']).read_bytes()) for e in report['files'] if e['path'].endswith('.insm') and Mesh((payload/e['path']).read_bytes()).sockets)
    sockets={s['name']:s for s in body.sockets}
    assert len(sockets)>26
    for a in plan['objects']:
        if a.get('socket_preset'):
            assert a['socket'] in sockets
            obj=next(o for o in scan['objects'] if o['name']==a['name']);x,y,z=obj['location']
            assert max(abs(p-q) for p,q in zip(sockets[a['socket']]['position'],[x/1000,z/1000,y/1000]))<1e-7
    for slot in layout.findall('Socket'):
        assert slot.get('Name') in sockets
        assert max(abs(a-b) for a,b in zip(layout_transform(slot),sockets[slot.get('Name')]['position']+sockets[slot.get('Name')]['quaternion']))<1e-6
    weapon=loadout.find('./Mount[@Weapon="TurretGunMK7"]');assert weapon is not None and weapon.get('GroupID')=='3'
    assert loadout.find('Actor').text==plan['name']
    for socket,effect in [('s_main_top_left','P_CruiserThruster'),('s_main_top_right','P_CarrierThruster')]:
        t=thrust.find('./Thruster[@Name="'+socket+'"]');g=thrust.find('./Group[@ID="'+t.get('GroupID')+'"]')
        assert g.find('Particles').get('Name').endswith(effect)
    weapons=ET.parse(payload/'Dev/Config/Weapons.xml').getroot()
    assert weapons.find('./Weapon[ID="TurretGunMK7"]/Actor[@Class="'+plan['name']+'"]') is not None
    assert actor.find('./CClientNodeComponent/Object/Socket[@Name="'+new_socket_name('CanopyShell')+'"]') is not None
    subprocess.run([sys.executable,str(base/'tools/validate_new_actor.py'),str(game),str(output)],check=True)
    if extension=='blend':
        assigned=folder/'AssignedSockets.blend';convert_custom_file(game,blender_path(),plan,assigned,prepare=True)
        reopened=inspect_custom_file(game,assigned,blender_path());replay=default_plan(reopened)
        assert not validate_plan(replay,reopened)[0]
        assert sum(bool(a.get('socket_preset')) and a['role']=='socket' for a in replay['objects'])==5
        stage_new_actor(game,assigned,blender_path(),folder/'assigned-replay-mod')
        replay_report=json.loads((folder/'assigned-replay-mod/mod.json').read_text())
        assert {e['path']:e['after'] for e in replay_report['files']}=={e['path']:e['after'] for e in report['files']}
    print('SOCKET IMPORT PASSED',extension,len(scan['socket_catalog']['presets']),'presets;',len(sockets),'exported sockets',flush=True)
for ref,sha in before.items():assert digest((game/ref).read_bytes())==sha
