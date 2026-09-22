import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from ibworkbench.formats import Mesh, texture_png
from ibworkbench.texture_writeback import encode_texture
from test_core import triangle


class ReplacementTests(unittest.TestCase):
    def test_new_topology_and_socket_tail(self):
        for width in (2, 4):
            old = Mesh(triangle(width))
            vertices = np.array([[0,0,0], [2,0,0], [2,1,0], [0,1,0]], np.float32)
            faces = np.array([[0,1,2], [0,2,3]])
            rebuilt = Mesh(old.rebuild(vertices, faces, {}, [0,0]))
            np.testing.assert_array_equal(rebuilt.faces, faces)
            np.testing.assert_array_equal(rebuilt.positions, vertices)
            self.assertEqual(rebuilt.width, width)
            self.assertEqual(rebuilt.groups[0]['material'], 123)
            self.assertEqual(rebuilt.data[-38:], old.data[-38:])
            self.assertEqual(struct.unpack_from('<6d', rebuilt.data, 22), (0,0,0,2,1,0))
            self.assertEqual(rebuilt.patch(), rebuilt.data)

    def test_invalid_topology_and_material(self):
        old = Mesh(triangle())
        for faces, slots in (([[0,0,1]], [0]), ([[0,1,99]], [0]), ([[0,1,2]], [5]), ([[0.,1.,2.]], [0])):
            with self.assertRaises(ValueError): old.rebuild(old.positions, faces, {}, slots)

    def test_index_width_promoted_preserves_high_indices_and_sockets(self):
        old = Mesh(triangle())
        vertices = np.zeros((65537,3), np.float32)
        vertices[65536] = [1,2,3]
        faces = np.array([[0,1,65536]])
        rebuilt = Mesh(old.rebuild(vertices, faces, {}, [0]))
        self.assertEqual(rebuilt.width, 4)
        np.testing.assert_array_equal(rebuilt.faces, faces)
        np.testing.assert_array_equal(rebuilt.positions, vertices)
        self.assertEqual(rebuilt.groups[0]['material'], 123)
        self.assertEqual(rebuilt.data[-38:], old.data[-38:])
        self.assertEqual(rebuilt.patch(), rebuilt.data)

    def test_65536_vertices_still_fit_16_bit_indices(self):
        old = Mesh(triangle())
        rebuilt = Mesh(old.rebuild(np.zeros((65536,3)), [[0,1,65535]], {}, [0]))
        self.assertEqual(rebuilt.width, 2)
        self.assertEqual(rebuilt.faces[0,2], 65535)


def texture(dxgi=98, mips=3):
    header = bytearray(56)
    header[:4] = b'TXB1'
    struct.pack_into('<7I', header, 4, 4,4,0,1,0,mips,dxgi)
    header[32:52] = bytes(range(20))
    return bytes(header)


class TextureTests(unittest.TestCase):
    def test_bc7_becomes_rgba_with_mips(self):
        pixels = np.full((4,4,4), [.2,.4,.6,1], np.float32)
        data = encode_texture(texture(), pixels)
        self.assertEqual(struct.unpack_from('<2I',data,24), (3,28))
        self.assertEqual(len(data), 56+4*(16+4+1))
        self.assertEqual(struct.unpack_from('<I',data,52)[0], len(data)-56)
        self.assertEqual(data[32:52], texture()[32:52])
        with tempfile.TemporaryDirectory() as folder:
            txb, png = Path(folder)/'edited.txb', Path(folder)/'decoded.png'
            txb.write_bytes(data)
            texture_png(txb,png)
            np.testing.assert_array_equal(np.array(Image.open(png))[0,0], [51,102,153,255])

    def test_srgb_mipmap_and_resize(self):
        pixels = np.ones((2,2,4), np.float32)
        pixels[0,:,:3] = 0
        data = encode_texture(texture(99), pixels)
        self.assertEqual(struct.unpack_from('<2I',data,4), (2,2))
        self.assertEqual(struct.unpack_from('<2I',data,24), (2,29))
        self.assertEqual(list(data[-4:]), [188,188,188,255])

    def test_signed_normal_map(self):
        pixels = np.full((1,1,4), [.5,.5,1,1], np.float32)
        data = encode_texture(texture(84), pixels)
        self.assertEqual(struct.unpack_from('<I',data,28)[0],31)
        self.assertEqual(list(data[-4:]),[0,0,127,127])

    def test_invalid_or_unsupported_image(self):
        for source, pixels in ((texture(10), np.zeros((2,2,4))), (texture(), np.full((1,1,4), np.nan)), (texture(), np.full((1,1,4), 2))):
            with self.assertRaises(ValueError): encode_texture(source, pixels)


class TextureInstallTests(unittest.TestCase):
    def test_texture_install_restore(self):
        import json
        from ibworkbench.mods import atomic_write, install, restore
        from ibworkbench.formats import digest
        ref = 'Dev/test/image.txb'
        before = encode_texture(texture(), np.zeros((2,2,4)))
        after = encode_texture(texture(), np.ones((2,2,4)))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            atomic_write(root/'game'/ref, before)
            atomic_write(root/'mod'/'payload'/ref, after)
            atomic_write(root/'mod'/'mod.json', json.dumps(dict(version=1,files=[dict(path=ref,before=digest(before),after=digest(after))])).encode())
            backup = install(root/'mod',root/'game',root/'backups')
            self.assertEqual((root/'game'/ref).read_bytes(), after)
            restore(backup,root/'game')
            self.assertEqual((root/'game'/ref).read_bytes(), before)
