from pathlib import Path
import json
import os
import struct
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import numpy as np
from ibworkbench.formats import Mesh, Assets, asset_hash, digest, inside, material_instance, xml_read, texture_png
from ibworkbench.mods import atomic_write, install, restore
from ibworkbench.project import transform, Project


def triangle(width=2):
    data=bytearray(260)
    data[:6]=b'insm\x04\x00'
    struct.pack_into('<4I',data,6,3,3,1,1)
    struct.pack_into('<6d',data,22,0,0,0,1,1,0)
    struct.pack_into('<I',data,82,5)
    struct.pack_into('<H',data,212,12)
    struct.pack_into('<3H',data,254,12,12,1)
    data += struct.pack('<9f',0,0,0,1,0,0,0,1,0)
    data += struct.pack('<3'+('H' if width==2 else 'I'),0,1,2)
    data += struct.pack('<B5I6f',1,0,0,3,3,123,0,0,0,1,1,0)
    data += struct.pack('<I',6)+b's_test'+struct.pack('<7f',0,0,0,0,0,0,1)
    return bytes(data)


class FormatTests(unittest.TestCase):
    def test_hash(self):
        self.assertEqual(asset_hash('Ships/SFC-Fighter/SM_SFC_Fighter_exterior_no_cockpit_Lod0'),0x8f41414a)
        self.assertEqual(asset_hash('gui/screens/t_portraitsheet'),0xe13166ed)

    def test_both_index_widths_under_65536(self):
        for width in (2,4):
            mesh=Mesh(triangle(width))
            self.assertEqual(mesh.width,width)
            self.assertEqual(mesh.patch(mesh.positions),mesh.data)

    def test_exact_tail_required(self):
        for data in (triangle()[:-1],triangle()+b'extra',b'not a mesh'):
            with self.assertRaises(ValueError): Mesh(data)

    def test_edit_updates_bounds_preserves_tail(self):
        mesh=Mesh(triangle())
        values=mesh.positions.copy()
        values[1,0]=2
        new=Mesh(mesh.patch(values))
        self.assertEqual(struct.unpack_from('<d',new.data,46)[0],2)
        self.assertEqual(new.data[-38:],mesh.data[-38:])
        np.testing.assert_array_equal(new.faces,mesh.faces)

    def test_nonfinite_rejected(self):
        mesh=Mesh(triangle())
        values=mesh.positions.copy()
        values[0,0]=float('nan')
        with self.assertRaises(ValueError): mesh.patch(values)

    def test_socket_patch(self):
        mesh=Mesh(triangle())
        new=Mesh(mesh.patch(sockets={'s_test':[1,2,3,0,0,0,1]}))
        self.assertEqual(new.sockets[0]['position'],[1,2,3])
        np.testing.assert_array_equal(new.positions,mesh.positions)

    def test_path_containment(self):
        with tempfile.TemporaryDirectory() as temp:
            for path in ('../escape','../../escape',temp):
                with self.assertRaises(ValueError): inside(temp,path)
            self.assertTrue(inside(temp,'Dev/file.insm').is_relative_to(temp))

    def test_xml_entities_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'test.xml'
            atomic_write(file,b'<!DOCTYPE a [<!ENTITY foo SYSTEM "file:///secrets">]><a/>')
            with self.assertRaises(ValueError): xml_read(file)

    def test_transforms(self):
        engine=transform(ET.fromstring('<Link><position x="1" y="2" z="3"/><rotation x=".1" y=".2" z=".3" w=".9"/></Link>'))
        maxnode=transform(ET.fromstring('<Link><position x="1" y="2" z="3" Type="3dsMax"/><rotation x=".1" y=".2" z=".3" w=".9" Type="3dsMax"/></Link>'))
        self.assertEqual(engine['position'],[1000,3000,2000])
        self.assertEqual(engine['quaternion'],[.9,-.1,-.3,-.2])
        self.assertEqual(maxnode['position'],[1000,2000,3000])
        self.assertEqual(maxnode['quaternion'],[.9,-.1,-.2,-.3])


class SkinTests(unittest.TestCase):
    def make_project(self,folder):
        p=Project(None,folder,lambda _:None)
        p.result['materials']={'original':dict(id='original',params={},editable={})}
        p.result['meshes']={'mesh':dict(materials=['original'])}
        return p

    def test_colormap_preview_keeps_original_material(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.make_project(folder)
            p.skin=dict(name='test',materials={},color_map='texture',paint_slots=[0])
            p.texture=lambda _: '12345678'
            p.skin_mesh('mesh')
            item=p.result['meshes']['mesh']
            self.assertEqual(item['original_materials'],['original'])
            mat=p.result['materials'][item['materials'][0]]
            self.assertEqual(mat['params']['IB_RuntimeColorMap']['texture'],'12345678')
            self.assertEqual(p.result['materials']['original']['params'],{})
            before=list(item['materials'])
            p.skin_mesh('mesh')
            self.assertEqual(item['materials'],before)

    def test_material_override_does_not_invent_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.make_project(folder)
            p.skin=dict(name='test',materials={0:'replacement',4:'absent'},color_map=None,paint_slots=[])
            p.material=lambda key:f'{key:08x}'
            p.skin_mesh('mesh')
            self.assertEqual(p.result['meshes']['mesh']['materials'],[f'{asset_hash("replacement"):08x}'])


class ModTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.game=self.root/'game'
        self.mod=self.root/'mod'
        self.files=[]
        for name in ('a','b'):
            ref='Dev/test/'+name+'.xml'
            atomic_write(self.game/ref,b'<old/>')
            atomic_write(self.mod/'payload'/ref,b'<new/>')
            self.files.append(dict(path=ref,before=digest(b'<old/>'),after=digest(b'<new/>')))
        self.manifest()

    def manifest(self):
        atomic_write(self.mod/'mod.json',json.dumps(dict(version=1,files=self.files)).encode())

    def tearDown(self): self.temp.cleanup()

    def test_install_restore(self):
        backup=install(self.mod,self.game,self.root/'backups')
        self.assertEqual((self.game/self.files[0]['path']).read_bytes(),b'<new/>')
        restore(backup,self.game)
        self.assertEqual((self.game/self.files[0]['path']).read_bytes(),b'<old/>')

    def test_conflict_no_partial_writes(self):
        atomic_write(self.game/self.files[1]['path'],b'<user_edit/>')
        with self.assertRaises(ValueError): install(self.mod,self.game,self.root/'backups')
        self.assertEqual((self.game/self.files[0]['path']).read_bytes(),b'<old/>')

    def test_restore_conflict(self):
        backup=install(self.mod,self.game,self.root/'backups')
        atomic_write(self.game/self.files[1]['path'],b'<later_mod/>')
        with self.assertRaises(ValueError): restore(backup,self.game)
        self.assertEqual((self.game/self.files[0]['path']).read_bytes(),b'<new/>')

    def test_duplicate_target(self):
        self.files.append(self.files[0])
        self.manifest()
        with self.assertRaises(ValueError): install(self.mod,self.game,self.root/'backups')

    def test_traversal(self):
        self.files[0]['path']='Dev/../../escape.xml'
        self.manifest()
        with self.assertRaises(ValueError): install(self.mod,self.game,self.root/'backups')

    def test_mid_install_rollback(self):
        from ibworkbench import mods
        original=mods.atomic_write
        def failing(path,data):
            if Path(path)==self.game/self.files[1]['path'] and data==b'<new/>':
                raise OSError('simulated write failure')
            original(path,data)
        with patch.object(mods,'atomic_write',failing):
            with self.assertRaises(OSError): install(self.mod,self.game,self.root/'backups')
        for entry in self.files:
            self.assertEqual((self.game/entry['path']).read_bytes(),b'<old/>')


GAME=Path(os.environ.get('IB_GAME_ROOT','A:/Steam/steamapps/common/Infinity Battlescape'))
@unittest.skipUnless((GAME/'Dev/toc.xml').exists(),'Game not installed')
class RealAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.assets=Assets(GAME)

    def test_low_lod_is_32bit(self):
        mesh=Mesh((GAME/'Dev/Ships/SFC-Fighter/f476a494.insm').read_bytes())
        self.assertLess(mesh.nv,65536)
        self.assertEqual(mesh.width,4)
        self.assertEqual(mesh.patch(mesh.positions),mesh.data)

    def test_render_groups_sockets(self):
        mesh=Mesh(self.assets.resolve('Ships/SFC-Fighter/SM_SFC_Fighter_exterior_no_cockpit_Lod0','.insm').read_bytes())
        self.assertEqual(len(mesh.sockets),26)
        self.assertEqual(sum(g['count'] for g in mesh.groups),mesh.ni)
        self.assertEqual(mesh.patch(mesh.positions),mesh.data)
        for group in mesh.groups:
            _,params=material_instance(self.assets.resolve(group['material'],'.cmti').read_bytes())
            self.assertTrue(params)

    def test_texture_bc7(self):
        with tempfile.TemporaryDirectory() as temp:
            info=texture_png(GAME/'Dev/Common/Textures/953c3b2a.txb',Path(temp)/'image.png')
            self.assertEqual(info['dxgi'],98)
            self.assertEqual(info['width'],512)


if __name__=='__main__': unittest.main()
