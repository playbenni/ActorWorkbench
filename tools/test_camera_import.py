"""Check actual camera conversion, import scale, and assigned Blend replay."""
import json
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ibworkbench.runner import inspect_custom_file,convert_custom_file,stage_new_actor,blender_path
from ibworkbench.import_plan import default_plan,validate_plan
from ibworkbench.socket_types import COCKPIT_CAMERA,new_socket_name
base=Path(__file__).resolve().parent.parent;folder=base/'samples/camera-validation'
game=Path('A:/Steam/steamapps/common/Infinity Battlescape')
scan=inspect_custom_file(game,folder/'CameraSource.blend',blender_path())
(folder/'inspection.json').write_text(json.dumps(scan,indent=2),encoding='utf8')
plan=default_plan(scan);plan.update(name='CameraPositionTest',scale=.5)
previous=json.loads((base/'samples/import-ui-validation/blend-recipe.json').read_text('utf8'))
mapping={a['name']:a for a in previous['objects']}
for a in plan['objects']:
    if a['name'] in mapping:a.update(mapping[a['name']])
    if a['name']=='Pilot eye':a.update(role='socket',socket=new_socket_name(a['name']),socket_preset=COCKPIT_CAMERA)
for m in plan['materials']:m['resolution']=128
assert not validate_plan(plan,scan)[0]
(folder/'recipe.json').write_text(json.dumps(plan,indent=2),encoding='utf8')
convert_custom_file(game,blender_path(),plan,folder/'mod')
def check(output):
    report=json.loads((output/'mod.json').read_text())
    actor=ET.parse(output/'payload'/report['actor']).getroot()
    for path in ('./CClientCameraViewComponent/Camera[@Type="Internal"]/ViewPosition','./CClientInternalCockpitComponent/ViewPosition'):
        got=[float(actor.find(path).get(k)) for k in 'XYZ']
        assert max(abs(a-b) for a,b in zip(got,[0,.006,.0035]))<1e-8,got
    assert not any(e['path'] in ('Dev/Config/Weapons.xml','Dev/Config/ShipSystems.xml') for e in report['files'])
    return report
report=check(folder/'mod')
assigned=folder/'AssignedCamera.blend';convert_custom_file(game,blender_path(),plan,assigned,prepare=True)
again=inspect_custom_file(game,assigned,blender_path());replay=default_plan(again)
assert not validate_plan(replay,again)[0]
assert sum(a['role']=='socket' and a.get('socket_preset')==COCKPIT_CAMERA for a in replay['objects'])==1
stage_new_actor(game,assigned,blender_path(),folder/'replay-mod')
check(folder/'replay-mod')
print('CAMERA IMPORT PASSED: parent/world transform, scale .5, both camera positions, saved-scene replay, no equipment registry edits')
