import json
import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
import xml.etree.ElementTree as ET
from cryptography.exceptions import InvalidTag
from ibworkbench.editor_package import encode,encrypt,decrypt,matrix,rotation,quaternion,export_package,CollisionCatalog


class PackageTests(unittest.TestCase):
    def test_encryption_and_authentication(self):
        data=encrypt(b'IBS1 test')
        self.assertEqual(decrypt(data),b'IBS1 test')
        self.assertNotEqual(data,encrypt(b'IBS1 test'))
        with self.assertRaises(InvalidTag): decrypt(data[:-1]+bytes([data[-1]^1]))

    def test_editor_layout_without_bounds_or_lods(self):
        meshes=[dict(id='test',component='test.xml',positions=np.zeros((3,3)),indices=np.array([[0,1,2]]))]
        raw=encode(meshes,{'Test':[[0,0,0,0,0,0,0,1,1]]})
        magic,size,pc,ic=struct.unpack_from('<4sIII',raw)
        self.assertEqual((magic,pc,ic),(b'IBS1',9,3))
        meta=json.loads(raw[16:16+size])
        self.assertEqual(set(meta),{'version','meshes','assemblies'})
        self.assertNotIn('boundsMin',meta['meshes'][0])
        self.assertEqual(len(raw),16+size+(-size)%4+4*(pc+ic))

    def test_max_transform_matches_editor(self):
        n=ET.fromstring('<Link><position x="1" y="2" z="3" Type="3dsMax"/><rotation x="0" y="0" z="0.70710678" w="0.70710678" Type="3dsMax"/></Link>')
        m=matrix(n)
        np.testing.assert_allclose(m[:3,3],[1,3,-2])
        q=quaternion(m[:3,:3])
        np.testing.assert_allclose(q,[0,-2**-.5,0,2**-.5],atol=1e-7)

    def test_half_turn_quaternions(self):
        for q in ([0,1,0,0],[0,0,1,0],[0,0,0,1],[1,0,0,0]):
            m=rotation(q)
            out=quaternion(m)
            np.testing.assert_allclose(rotation([out[3],*out[:3]]),m,atol=1e-7)

    def test_refuses_overwrite_before_loading_game(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'test.ibmesh'
            p.write_bytes(b'original')
            with self.assertRaises(ValueError): export_package('missing',[],p)
            self.assertEqual(p.read_bytes(),b'original')

    def test_nonuniform_mirror_baked_and_deduplicated(self):
        builder=CollisionCatalog(None)
        path=Path('mesh.insm')
        points=np.array([[1,0,0],[0,1,0],[0,0,1]],dtype=float)
        builder.meshes=[dict(id='mesh',component='component.xml',positions=points,indices=np.array([[0,1,2]]))]
        builder.by_path[str(path).lower()]=0
        world=np.diag([-2.,3.,4.,1.])
        world[:3,3]=[10,20,30]
        instances=[]
        builder.add_mesh(path,Path('component.xml'),world,instances)
        builder.add_mesh(path,Path('component.xml'),world,instances)
        self.assertEqual(len(builder.meshes),2)
        self.assertEqual(instances[0],instances[1])
        self.assertEqual(instances[0],[1,10,20,30,0,0,0,1,1])
        np.testing.assert_allclose(builder.meshes[1]['positions'],points@world[:3,:3].T)
        np.testing.assert_array_equal(builder.meshes[1]['indices'],[[0,2,1]])
