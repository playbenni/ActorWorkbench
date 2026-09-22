import copy
import unittest
from pathlib import Path
from ibworkbench.import_plan import default_plan,validate_plan
from ibworkbench.new_actor import add_mesh_roles
import xml.etree.ElementTree as ET


def inspection():
    return dict(source=str(Path('source.blend').resolve()),source_sha256='abc',suggested_scale=1,sockets=['gun','engine'],
                objects=[dict(name=name,type='MESH',faces=12,collections=[],slots=[dict(index=0,material='Hull')]) for name in ('body','bunda','low')],
                materials=[dict(name='Hull',issue=None),dict(name='Glass',issue='Transmission is unsupported')])


class ImportPlanTests(unittest.TestCase):
    def setUp(self):
        self.scan=inspection();self.plan=default_plan(self.scan)
        self.plan['objects'][1]['role']='collision';self.plan['objects'][2]['role']='ignore'

    def test_arbitrary_names_and_ignored_materials(self):
        self.plan['materials'][1]['source_material']='Glass'
        errors,warnings=validate_plan(self.plan,self.scan)
        self.assertEqual(errors,[])
        self.assertTrue(any('2 unassigned sockets' in w for w in warnings))

    def test_source_change_missing_collision_and_invalid_material(self):
        self.plan['source_sha256']='old'
        self.plan['objects'][1]['role']='ignore'
        self.plan['materials'][0]['source_material']='Glass'
        errors,_=validate_plan(self.plan,self.scan)
        self.assertTrue(any('changed' in e for e in errors))
        self.assertTrue(any('collision' in e for e in errors))
        self.assertTrue(any('Transmission' in e for e in errors))

    def test_explicit_simplification(self):
        self.plan['materials'][0].update(source_material='Glass',mode='diffuse')
        errors,warnings=validate_plan(self.plan,self.scan)
        self.assertFalse(errors)
        self.assertTrue(any('links are omitted' in w for w in warnings))

    def test_lod_and_cockpit_dependencies(self):
        self.plan['objects'][2]['role']='lod2'
        self.assertTrue(any('consecutive' in e for e in validate_plan(self.plan,self.scan)[0]))
        self.plan['objects'][2]['role']='cockpit_collision'
        self.assertTrue(any('interior cockpit' in e for e in validate_plan(self.plan,self.scan)[0]))

    def test_duplicate_and_required_sockets(self):
        self.plan['default_sockets']=False
        self.assertTrue(any('Assign all sockets' in e for e in validate_plan(self.plan,self.scan)[0]))
        for index in (0,2):self.plan['objects'][index].update(role='socket',socket='gun')
        self.assertTrue(any('more than once' in e for e in validate_plan(self.plan,self.scan)[0]))

    def test_material_remap_resolution_and_xml_roles(self):
        self.plan['materials'][0]['resolution']=256
        self.assertFalse(validate_plan(self.plan,self.scan)[0])
        root=ET.fromstring('<ActorConfig><CClientNodeComponent><Object Mesh="main"/></CClientNodeComponent></ActorConfig>')
        cockpit=ET.fromstring('<CClientInternalCockpitComponent><ViewPosition X="1" Y="2" Z="3"/><Head><Yaw Min="-110" Max="110"/></Head><MFD ID="0" SegID="6"/></CClientInternalCockpitComponent>')
        add_mesh_roles(root,{1:'lower',2:'lowest'},'outer','inner','Dev/cockpit.insm',cockpit)
        self.assertEqual(root.find('./CClientNodeComponent/Object/LOD[@Level="2"]').get('Mesh'),'lowest')
        self.assertEqual(root.find('./CClientExternalCockpitComponent/Object').get('Mesh'),'outer')
        self.assertEqual(root.findtext('./CClientInternalCockpitComponent/CockpitBody/CollisionFile'),'$Dev/cockpit.insm')
        self.assertEqual(root.find('./CClientInternalCockpitComponent/ViewPosition').get('Y'),'2')
        self.assertIsNone(root.find('.//MFD'))

    def test_malformed_recipe_reports_errors_without_crashing(self):
        for value in ([],None,{'objects':None},dict(self.plan,materials=[{}]),dict(self.plan,source=None)):
            self.assertTrue(validate_plan(value,self.scan)[0])
        self.plan['objects'][2]['role']='lod_invalid'
        self.assertTrue(any('Unknown role' in e for e in validate_plan(self.plan,self.scan)[0]))

    def test_missing_unused_slot_is_rejected_before_role_change(self):
        self.plan['materials'].pop()
        self.assertTrue(any('Every mesh slot' in e for e in validate_plan(self.plan,self.scan)[0]))

    def test_prepared_scene_does_not_reactivate_ignored_geometry_or_socket_sources(self):
        self.scan['objects'][2].update(collections=['Ignored'],socket='gun')
        generated=default_plan(self.scan)
        self.assertEqual(generated['objects'][2]['role'],'ignore')
