import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
import numpy as np
from test_core import triangle
from ibworkbench.formats import Mesh, asset_hash, digest, material_instance
from ibworkbench.new_actor import actor_name, material_bytes, layout_materials, pack_channels, register_assets, SHADER
from ibworkbench.mods import install, restore, atomic_write


class NewActorFormatTests(unittest.TestCase):
    def test_material_instances_and_new_groups(self):
        data=material_bytes({'T_Skin':('texture',123),'S_EmissivePower':('scalar',2),'V_DetailColorStrength':('vector',[0,0,0,0])})
        parent,params=material_instance(data)
        self.assertEqual(parent,SHADER)
        self.assertEqual(params['T_Skin']['value'],123)
        old=Mesh(triangle())
        changed=layout_materials(old,[432,567,890])
        self.assertEqual([g['material'] for g in changed.groups],[432,567,890])
        result=Mesh(changed.rebuild(old.positions,old.faces,{},[2]))
        self.assertEqual(result.groups[2]['count'],3)
        self.assertEqual(result.data[-38:],old.data[-38:])

    def test_principled_channel_packing(self):
        base=np.full((2,2,3),.2,np.float32)
        emission=np.zeros_like(base);emission[0,0]=[0,1,2]
        normals=np.full_like(base,[.5,.7,1])
        skin,data,normal,power,adapted=pack_channels(base,np.full((2,2),.4),np.full((2,2),.8),emission,normals)
        self.assertTrue(adapted)
        np.testing.assert_allclose(skin[:,:,3],.4)
        np.testing.assert_allclose(data[:,:,0],1)
        np.testing.assert_allclose(data[:,:,1],.8)
        self.assertLess(normal[0,0,1],.5)
        decoded=np.where(skin[:,:,:3]<=.04045,skin[:,:,:3]/12.92,((skin[:,:,:3]+.055)/1.055)**2.4)
        np.testing.assert_allclose(decoded*data[:,:,2,None]*power*.1,emission,atol=1e-5)
        np.testing.assert_allclose(decoded[1,1],base[1,1],atol=1e-6)

    def test_registry_preserves_entries_and_rejects_collisions(self):
        root=ET.fromstring('<TableOfContents><Entry Name="123" Type="42"><File>$Dev/base.insm</File></Entry></TableOfContents>')
        new=register_assets(root,[('Mods/Test/Render','Dev/Mods/Test/new.insm')])
        self.assertEqual(len(root),1)
        self.assertEqual(ET.tostring(root[0]),ET.tostring(new[0]))
        self.assertEqual(int(new[1].get('Name')) & 0xffffffff,asset_hash('Mods/Test/Render'))
        with self.assertRaises(ValueError):register_assets(new,[('Mods/Test/Render','Dev/different.insm')])
        for name in ('Interceptor','../Ship','Ship Name','a','A/B'):
            with self.assertRaises(ValueError):actor_name(name)


class AdditiveModTests(unittest.TestCase):
    def setup_mod(self,root):
        game,mod=root/'game',root/'mod'
        atomic_write(game/'Dev/toc.xml',b'original registry')
        files=[]
        for path,old,new in [('Dev/toc.xml',b'original registry',b'new registry'),('Dev/Mods/Ship/new.insm',None,b'new mesh')]:
            atomic_write(mod/'payload'/path,new)
            files.append(dict(path=path,before=digest(old) if old else None,after=digest(new)))
        atomic_write(mod/'mod.json',json.dumps(dict(version=2,files=files)).encode())
        return game,mod

    def test_add_install_restore_preserves_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,mod=self.setup_mod(root)
            backup=install(mod,game,root/'backups')
            self.assertEqual((game/'Dev/Mods/Ship/new.insm').read_bytes(),b'new mesh')
            restore(backup,game)
            self.assertFalse((game/'Dev/Mods/Ship/new.insm').exists())
            self.assertEqual((game/'Dev/toc.xml').read_bytes(),b'original registry')

    def test_existing_path_conflict_changes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,mod=self.setup_mod(root)
            atomic_write(game/'Dev/Mods/Ship/new.insm',b'user file')
            with self.assertRaises(ValueError):install(mod,game,root/'backups')
            self.assertEqual((game/'Dev/toc.xml').read_bytes(),b'original registry')

    def test_restore_refuses_edited_new_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,mod=self.setup_mod(root)
            backup=install(mod,game,root/'backups')
            atomic_write(game/'Dev/Mods/Ship/new.insm',b'user edit')
            with self.assertRaises(ValueError):restore(backup,game)
            self.assertEqual((game/'Dev/toc.xml').read_bytes(),b'new registry')

    def test_install_rolls_back_created_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,mod=self.setup_mod(root)
            manifest=json.loads((mod/'mod.json').read_text());manifest['files'].reverse()
            (mod/'mod.json').write_text(json.dumps(manifest))
            real=atomic_write
            def failing(path,data):
                if Path(path)==game/'Dev/toc.xml' and data==b'new registry':raise OSError('simulated disk failure')
                real(path,data)
            with patch('ibworkbench.mods.atomic_write',side_effect=failing):
                with self.assertRaises(OSError):install(mod,game,root/'backups')
            self.assertFalse((game/'Dev/Mods/Ship/new.insm').exists())
            self.assertEqual((game/'Dev/toc.xml').read_bytes(),b'original registry')
