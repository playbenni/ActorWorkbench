"""End-to-end import assignments; never installs into the real game."""
import json
import shutil
import struct
import sys
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ibworkbench.runner import inspect_custom_file,convert_custom_file,blender_path
from ibworkbench.import_plan import default_plan,validate_plan
from ibworkbench.formats import Assets,Mesh,digest,material_instance
from ibworkbench.mods import install,restore
from ibworkbench.project import prepare

base=Path(__file__).resolve().parent.parent
folder=base/'samples/import-ui-validation'
game=Path('A:/Steam/steamapps/common/Infinity Battlescape')
blender=blender_path()
registries={ref:digest((game/ref).read_bytes()) for ref in ('Dev/toc.xml','Dev/Config/ActorsList.xml')}
results=[]
for extension in sys.argv[1:] or ['blend','glb']:
    source=folder/('arbitrary.'+extension)
    original=digest(source.read_bytes())
    scan=inspect_custom_file(game,source,blender)
    (folder/(extension+'-inspection.json')).write_text(json.dumps(scan,indent=2),encoding='utf8')
    plan=default_plan(scan);plan.update(name='Assigned'+extension.title()+'Test',default_sockets=False)
    roles={'bunda':'collision','far_away_shape':'lod1','CanopyShell':'exterior_cockpit',
           'Console':'interior_cockpit','CockpitHitHull':'cockpit_collision','unused_bolt':'ignore',
           'mystery_nozzle':'socket'}
    for obj in plan['objects']:
        if obj['name'] in roles:obj['role']=roles[obj['name']]
        if obj['name']=='mystery_nozzle':obj['socket']='s_main_top_left'
    for slot in plan['materials']:
        slot['resolution']=256 if slot['object']=='Hull' else 128
        if slot['object']=='far_away_shape':slot['source_material']='Trim - Principled'
        if slot['object']=='CanopyShell':slot['mode']='diffuse'
    errors,warnings=validate_plan(plan,scan)
    assert not errors,errors
    (folder/(extension+'-recipe.json')).write_text(json.dumps(plan,indent=2),encoding='utf8')
    output=folder/(extension+'-mod')
    convert_custom_file(game,blender,plan,output)
    if extension=='blend':convert_custom_file(game,blender,plan,folder/'Assigned.blend',prepare=True)
    report=json.loads((output/'mod.json').read_text())
    with tempfile.TemporaryDirectory(prefix='ibaw-custom-check-') as temp:
        root=Path(temp)/'game';source_assets=Assets(game)
        refs=['Dev/toc.xml','Engine/toc.xml','Dev/Config/ActorsList.xml','Dev/config/thrusters/FighterThrusters.xml']
        refs += [entry['path'] for entry in report['requires']]
        refs += [source_assets.relative(source_assets.resolve(key,'.txb')) for key in (0xfb767ea4,0x35ed2a67)]
        for ref in set(refs):
            dest=root/ref;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(game/ref,dest)
        backup=install(output,root,Path(temp)/'backups')
        assets=Assets(root);meshes=[];texture_sizes=set()
        for entry in report['files']:
            path=root/entry['path'];data=path.read_bytes()
            assert digest(data)==entry['after']
            if path.suffix=='.txb':texture_sizes.add(struct.unpack_from('<II',data,4))
            if path.suffix=='.cmti':
                parent,params=material_instance(data);assert assets.resolve(parent,'.cmat').exists()
                for param in params.values():
                    if param['kind']=='texture':assert assets.resolve(param['value'],'.txb').exists()
            if path.suffix=='.insm':
                mesh=Mesh(data);assert mesh.nv and mesh.ni
                meshes.append(dict(path=entry['path'],vertices=mesh.nv,triangles=mesh.ni//3,slots=len(mesh.groups),sockets=len(mesh.sockets)))
                if mesh.sockets:
                    socket=next(s for s in mesh.sockets if s['name']=='s_main_top_left')
                    obj=next(o for o in scan['objects'] if o['name']=='mystery_nozzle')
                    p=obj['location'];expected=[p[0]/1000,p[2]/1000,p[1]/1000]
                    assert max(abs(x-y) for x,y in zip(expected,socket['position']))<1e-7
        actor=ET.parse(root/report['actor']).getroot()
        assert actor.find('.//Skin') is None and actor.find('.//Paint') is None
        assert actor.find('./CClientNodeComponent/Object/LOD[@Level="1"]') is not None
        assert actor.find('./CClientExternalCockpitComponent/Object') is not None
        assert actor.find('./CClientInternalCockpitComponent/Object') is not None
        assert max(float(v) for v in actor.find('./Meta/WorldBoxSize').attrib.values())<.02, 'Ignored outlier entered actor bounds'
        assert texture_sizes=={(128,128),(256,256)},texture_sizes
        project=prepare(root,report['actor'],Path(temp)/'textures',log=lambda _:None)
        assert len(meshes)==6,meshes
        assert project['counts']['Render']==2 and project['counts']['Collision']==2,project['counts']
        assert not any('not found' in w.lower() or 'missing socket' in w.lower() for w in project['warnings']),project['warnings']
        restore(backup,root)
        for entry in report['files']:
            target=root/entry['path']
            assert (not target.exists()) if entry['before'] is None else digest(target.read_bytes())==entry['before']
    assert digest(source.read_bytes())==original
    results.append(dict(format=extension,status='passed',meshes=meshes,counts=project['counts'],files=len(report['files'])))
for ref,expected in registries.items():assert digest((game/ref).read_bytes())==expected
(folder/'validation.json').write_text(json.dumps(results,indent=2),encoding='utf8')
print('CUSTOM IMPORT VALIDATED',json.dumps(results,indent=2),flush=True)
