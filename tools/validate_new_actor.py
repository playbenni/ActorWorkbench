"""Validate and install/restore a new-actor package on temporary files only."""
import json
import shutil
import sys
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ibworkbench.formats import Assets, Mesh, digest, material_instance, asset_hash
from ibworkbench.mods import install, restore
from ibworkbench.project import prepare

game=Path(sys.argv[1]);mod=Path(sys.argv[2])
report=json.loads((mod/'mod.json').read_text())
assert report['version']==2
before_registry={ref:digest((game/ref).read_bytes()) for ref in ('Dev/toc.xml','Dev/Config/ActorsList.xml')}
with tempfile.TemporaryDirectory(prefix='new-actor-validation-') as temporary:
    root=Path(temporary)/'game'
    source_assets=Assets(game)
    refs=['Dev/toc.xml','Engine/toc.xml','Dev/Config/ActorsList.xml','Dev/config/thrusters/FighterThrusters.xml']
    refs += [entry['path'] for entry in report['requires']]
    refs += [entry['path'] for entry in report['files'] if entry['before'] is not None]
    refs += [source_assets.relative(source_assets.resolve(key,'.txb')) for key in (0xfb767ea4,0x35ed2a67)]
    for ref in set(refs):
        dest=root/ref;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(game/ref,dest)
    backup=install(mod,root,Path(temporary)/'backups')
    assets=Assets(root)
    materials=[];meshes=[]
    for entry in report['files']:
        data=(root/entry['path']).read_bytes()
        assert digest(data)==entry['after']
        if entry['path'].endswith('.cmti'):
            parent,params=material_instance(data)
            assert assets.resolve(parent,'.cmat').exists()
            for param in params.values():
                if param['kind']=='texture':assert assets.resolve(param['value'],'.txb').exists()
            materials.append(entry['path'])
        if entry['path'].endswith('.insm'):
            m=Mesh(data)
            assert m.nv>0 and m.ni>0
            meshes.append(dict(path=entry['path'],vertices=m.nv,triangles=m.ni//3,slots=len(m.groups),sockets=len(m.sockets)))
    actor=ET.parse(root/report['actor']).getroot()
    assert actor.find('.//Skin') is None and actor.find('.//Paint') is None
    assert assets.resolve(actor.find('./CClientNodeComponent/Object').get('Mesh'),'.insm').exists()
    project=prepare(root,report['actor'],Path(temporary)/'textures',log=lambda _:None)
    assert project['counts']['Render']==1+int(actor.find('./CClientExternalCockpitComponent/Object') is not None)
    assert project['counts']['Collision']==1+int(actor.find('./CClientInternalCockpitComponent/CockpitBody/CollisionFile') is not None)
    assert project['counts'].get('LOD',0)==len(actor.findall('./CClientNodeComponent/Object/LOD'))
    assert project['counts'].get('Cockpit',0)==int(actor.find('./CClientInternalCockpitComponent/Object') is not None)
    assert not any('not found' in w.lower() or 'missing socket' in w.lower() for w in project['warnings'])
    restore(backup,root)
    for entry in report['files']:
        target=root/entry['path']
        if entry['before'] is None:assert not target.exists()
        else:assert digest(target.read_bytes())==entry['before']
for ref,expected in before_registry.items():assert digest((game/ref).read_bytes())==expected
print(json.dumps(dict(status='passed',new_actor=report['actor_name'],meshes=meshes,material_count=len(materials),roundtrip_counts=project['counts'],checks=['asset resolution','material texture references','new actor XML without team skins','Workbench re-import','temporary install and restore','real game registries unchanged']),indent=2))
