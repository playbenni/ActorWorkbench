import copy
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from test_core import triangle
from ibworkbench.formats import Mesh,digest
from ibworkbench.socket_types import with_sockets,preset_errors,build_socket_assets,new_socket_name,layout_transform,set_cockpit_camera,COCKPIT_CAMERA
from ibworkbench.import_plan import default_plan,validate_plan
from test_import_plan import inspection


class SocketTests(unittest.TestCase):
    def test_camera_updates_both_internal_views_and_preserves_external_views(self):
        actor=ET.fromstring('<ActorConfig><CClientCameraViewComponent><Camera Type="Internal"><ViewPosition X="1"/><ViewAngle X="0" Y="0"/></Camera><Camera Type="External"><ViewPosition X="9"/></Camera></CClientCameraViewComponent><CClientInternalCockpitComponent><ViewPosition X="2"/><Object Mesh="cockpit"/></CClientInternalCockpitComponent></ActorConfig>')
        external=ET.tostring(actor.find('./CClientCameraViewComponent/Camera[@Type="External"]'))
        position=[.001,.003,.002]
        settings=[dict(socket='s_aw_eye',socket_preset=COCKPIT_CAMERA)]
        payload,updates,notes=build_socket_assets(None,'Test',actor,{'s_aw_eye':position+[0,0,0,1]},settings,dict(presets=[dict(id=COCKPIT_CAMERA,kind='camera')]))
        self.assertEqual((payload,updates),({},{}))
        for path in ('./CClientCameraViewComponent/Camera[@Type="Internal"]/ViewPosition','./CClientInternalCockpitComponent/ViewPosition'):
            self.assertEqual([float(actor.find(path).get(k)) for k in 'XYZ'],position)
        self.assertEqual(ET.tostring(actor.find('./CClientCameraViewComponent/Camera[@Type="External"]')),external)
        self.assertEqual(actor.find('.//ViewAngle').get('Y'),'0')
        actor.remove(actor.find('CClientInternalCockpitComponent'))
        set_cockpit_camera(actor,[0,0,0])
        self.assertIsNone(actor.find('CClientInternalCockpitComponent'))

    def test_camera_requires_one_empty_and_a_separate_marker(self):
        catalog=dict(sha256='current',presets=[dict(id=COCKPIT_CAMERA,kind='camera')])
        assignments=[dict(socket='s_aw_a',socket_preset=COCKPIT_CAMERA),dict(socket='s_aw_b',socket_preset=COCKPIT_CAMERA)]
        self.assertTrue(any('only one' in e for e in preset_errors(assignments,catalog,[])))
        self.assertTrue(any('own marker' in e for e in preset_errors(assignments[:1],catalog,['s_aw_a'])))
        scan=inspection();scan['socket_catalog']=catalog
        plan=default_plan(scan);plan['objects'][1]['role']='collision'
        plan['objects'][2].update(role='socket',socket='s_aw_eye',socket_preset=COCKPIT_CAMERA)
        self.assertTrue(any('must be assigned to an Empty' in e for e in validate_plan(plan,scan)[0]))
        scan['objects'][2]['type']='EMPTY'
        self.assertFalse(validate_plan(plan,scan)[0])

    def test_changed_equipment_definition_stops_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'Dev/Config/Weapons.xml';path.parent.mkdir(parents=True)
            path.write_bytes(b'updated definitions')
            catalog=dict(presets=[],sources={'Dev/Config/Weapons.xml':digest(b'original definitions')})
            with self.assertRaisesRegex(ValueError,'changed during conversion'):
                build_socket_assets(root,'CustomShip',None,{},[],catalog)

    def test_variable_socket_table_survives_geometry_rebuild(self):
        for width in (2,4):
            mesh=Mesh(triangle(width));values={'s_engine':[1,2,3,0,0,0,1],'s_gun':[4,5,6,0,0,1,0]}
            updated=with_sockets(mesh,values)
            self.assertEqual([s['name'] for s in updated.sockets],list(values))
            final=Mesh(updated.rebuild(updated.positions,updated.faces,{},[0]))
            self.assertEqual(final.sockets[1]['position'],[4,5,6])
            self.assertFalse(with_sockets(mesh,{}).sockets)
        with self.assertRaises(ValueError):with_sockets(mesh,{'s_bad':[0,0,0,0,0,0,0]})

    def test_typed_socket_validation_and_stale_catalog(self):
        scan=inspection();scan['socket_catalog']=dict(sha256='current',presets=[dict(id='weapon:Gun',kind='weapon')])
        plan=default_plan(scan);plan['objects'][1]['role']='collision'
        plan['objects'][2].update(role='socket',socket='s_custom',socket_preset='weapon:Gun',socket_group=9)
        self.assertFalse(validate_plan(plan,scan)[0])
        plan['socket_catalog_sha256']='old'
        self.assertTrue(any('attachment definitions changed' in e for e in validate_plan(plan,scan)[0]))
        plan['objects'][2]['socket_group']=10
        self.assertTrue(any('weapon group' in e for e in validate_plan(plan,scan)[0]))
        plan['objects'][2]['socket_preset']='unavailable'
        self.assertTrue(any('unavailable' in e for e in validate_plan(plan,scan)[0]))
        self.assertNotEqual(new_socket_name('Foo'),new_socket_name('foo'))

    def test_custom_configs_mounts_and_permissions_preserve_stock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(ref,text):
                p=root/ref;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
            write('Dev/Config/thrusters/Fighter.xml','<ThrustModel><MLQ>4096</MLQ><Group ID="0"><Particles Name="old"/></Group><Thruster ID="0" Name="s_main" GroupID="0"/></ThrustModel>')
            write('Dev/Config/Ships/Layouts/InterceptorLayout.xml','<Layout><Actor>Interceptor</Actor><DisplayName>DEFAULT</DisplayName><Socket Name="s_old"><Size>Mk1</Size><Category>Weapons</Category><position x="1" y="2" z="3" Type="3dsMax"/></Socket></Layout>')
            write('Dev/Config/Ships/Loadouts/DefaultInterceptor.xml','<Loadout><Name>DefaultInterceptor</Name><Actor>Interceptor</Actor><DisplayName>DEFAULT</DisplayName><ShortDescr>x</ShortDescr><LayoutFile>x</LayoutFile><Mount HardpointName="s_old" Weapon="SmallGun" GroupID="0"/></Loadout>')
            weapons=write('Dev/Config/Weapons.xml','<Weapons><Weapon><ID>SmallGun</ID><Actor Class="Interceptor"/></Weapon><Weapon><ID>LargeGun</ID><Actor Class="Carrier"/></Weapon><Weapon><ID>OtherGun</ID><Actor Class="Carrier"/></Weapon></Weapons>')
            systems=write('Dev/Config/ShipSystems.xml','<ShipSystems><ShipSystem Name="LargeShield" Category="Shields" Class="MK6"><Actor Class="Carrier"/></ShipSystem><ShipSystem Name="OtherSystem" Category="Reactor" Class="MK6"><Actor Class="Carrier"/></ShipSystem></ShipSystems>')
            original={p:p.read_bytes() for p in (weapons,systems)}
            actor=ET.fromstring('<ActorConfig><CClientNodeComponent><Object><ThrusterModel ConfigFile="$Dev/Config/thrusters/Fighter.xml"/></Object></CClientNodeComponent><CHardpointComponent><Layout>$Config/Ships/Layouts/InterceptorLayout.xml</Layout><ExclusiveWeapons>true</ExclusiveWeapons><Group ID="0"/><Hardpoint ID="0"><Socket>s_old</Socket></Hardpoint></CHardpointComponent><CServerHardpointComponent><Loadout Name="DefaultInterceptor" Proba="100"/></CServerHardpointComponent></ActorConfig>')
            presets=[dict(id='big',kind='thruster',xml='<Group ID="2"><Range>14</Range><Particles Name="carrier" SizeScale="1" Length="4"/></Group>'),
                     dict(id='gun',kind='weapon',category='Weapons',size='MK7',weapon='LargeGun'),
                     dict(id='shield',kind='module',category='Shields',size='MK6',ships=['Carrier'])]
            settings=[dict(socket='s_main',socket_preset='big'),dict(socket='s_aw_gun',socket_preset='gun',socket_group=4),dict(socket='s_aw_shield',socket_preset='shield')]
            sockets={a['socket']:[.1,.2,.3,0,0,0,1] for a in settings}
            payload,updates,notes=build_socket_assets(root,'CustomShip',actor,sockets,settings,dict(presets=presets))
            thrust=ET.fromstring(payload['Dev/Config/thrusters/CustomShipThrusters.xml'])
            self.assertEqual(len(thrust.findall('Thruster')),1)
            group=next(g for g in thrust.findall('Group') if g.get('ID')==thrust.find('Thruster').get('GroupID'))
            self.assertEqual(group.find('Particles').get('Name'),'carrier')
            self.assertEqual(group.find('Particles').get('Length'),'4')
            loadout=ET.fromstring(payload['Dev/Config/Ships/Loadouts/AW_CustomShip_Default.xml'])
            self.assertEqual(loadout.find('Actor').text,'CustomShip')
            mount=next(m for m in loadout.findall('Mount') if m.get('Weapon')=='LargeGun')
            self.assertEqual(mount.get('GroupID'),'4');self.assertEqual(mount.get('HardpointName'),'s_aw_gun')
            layout=ET.fromstring(payload['Dev/Config/Ships/Layouts/CustomShipLayout.xml'])
            self.assertEqual(sockets['s_old'],[1,3,2,0,0,0,1])
            self.assertEqual(layout_transform(layout.find('Socket[@Name="s_aw_shield"]')),sockets['s_aw_shield'])
            self.assertEqual(len(actor.findall('./CHardpointComponent/Hardpoint')),3)
            self.assertIsNotNone(updates['Dev/Config/Weapons.xml'].find('./Weapon[ID="LargeGun"]/Actor[@Class="CustomShip"]'))
            self.assertIsNone(updates['Dev/Config/Weapons.xml'].find('./Weapon[ID="OtherGun"]/Actor[@Class="CustomShip"]'))
            self.assertIsNotNone(updates['Dev/Config/ShipSystems.xml'].find('./ShipSystem[@Name="LargeShield"]/Actor[@Class="CustomShip"]'))
            self.assertIsNone(updates['Dev/Config/ShipSystems.xml'].find('./ShipSystem[@Name="OtherSystem"]/Actor[@Class="CustomShip"]'))
            for p,before in original.items():self.assertEqual(p.read_bytes(),before)
