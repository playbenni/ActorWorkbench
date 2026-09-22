"""Strict readers, lossless patches and static replacement writers for INSM v4.

Patches preserve unknown bytes; full replacements reject unknown vertex channels.
"""
from pathlib import Path
import hashlib
import math
import re
import struct
import xml.etree.ElementTree as ET
import numpy as np


def digest(data):
    return hashlib.sha256(data).hexdigest()


def asset_hash(name):
    data = name.replace('\\', '/').lower().encode('utf8')
    h = 0x0BADF00D
    for i in range(0, len(data) // 4 * 4, 4):
        k = int.from_bytes(data[i:i+4], 'little') * 0xcc9e2d51 & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        h ^= k * 0x1b873593 & 0xffffffff
        h = ((h << 13) | (h >> 19)) & 0xffffffff
        h = (h * 5 + 0xe6546b64) & 0xffffffff
    tail = data[len(data) // 4 * 4:]
    if tail:
        k = int.from_bytes(tail, 'little') * 0xcc9e2d51 & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        h ^= k * 0x1b873593 & 0xffffffff
    h ^= len(data)
    h ^= h >> 16
    h = h * 0x85ebca6b & 0xffffffff
    h ^= h >> 13
    h = h * 0xc2b2ae35 & 0xffffffff
    return h ^ (h >> 16)


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError(f'Path escapes asset directory: {relative}')
    return path


def xml_read(path):
    data = Path(path).read_bytes()
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError(f'XML entity/doctype not supported: {path}')
    return ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))


class Assets:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not (self.root / 'Dev/toc.xml').is_file():
            raise ValueError('Choose the Infinity Battlescape installation folder (containing Dev).')
        self.index = {}
        for folder in ('Engine', 'Dev'):
            toc = self.root / folder / 'toc.xml'
            if toc.exists():
                for entry in xml_read(toc).findall('Entry'):
                    for file in entry.findall('File'):
                        path = self.path(file.text or '')
                        self.index[(int(entry.attrib['Name']) & 0xffffffff, path.suffix.lower())] = path

    def path(self, ref):
        ref = ref.strip().replace('\\', '/')
        if ref.startswith('$'):
            ref = ref[1:]
        if ref.split('/')[0].lower() not in ('dev', 'engine'):
            raise ValueError(f'Unsupported asset root: {ref}')
        return inside(self.root, ref)

    def resolve(self, name, suffix):
        key = (name if isinstance(name, int) else asset_hash(name), suffix)
        if key not in self.index:
            raise ValueError(f'Asset not found: {name} ({key[0]:08x}{suffix})')
        return self.index[key]

    def relative(self, path):
        return Path(path).resolve().relative_to(self.root).as_posix()


class Mesh:
    def __init__(self, data):
        self.data = bytes(data)
        if len(data) < 260 or data[:6] != b'insm\x04\x00':
            raise ValueError('Only INSM version 4 is supported')
        self.nv, self.ni, ng, ns = struct.unpack_from('<4I', data, 6)
        self.stride, stride2, _ = struct.unpack_from('<3H', data, 254)
        if not self.nv or self.ni % 3 or self.stride != stride2 or not 12 <= self.stride <= 256:
            raise ValueError('Invalid vertex declaration/counts')
        self.types = struct.unpack_from('<22I', data, 78)
        self.offsets = struct.unpack_from('<22H', data, 166)
        self.sizes = struct.unpack_from('<22H', data, 210)
        if self.types[1] != 5 or self.offsets[1] != 0 or self.sizes[1] != 12:
            raise ValueError('Unknown position declaration')
        self.index_start = 260 + self.nv * self.stride
        if self.index_start > len(data):
            raise ValueError('Truncated vertices')
        self.positions = self.attribute(1)
        if not np.isfinite(self.positions).all():
            raise ValueError('Non-finite positions')
        candidates = []
        for width in (2, 4):
            try:
                cursor = self.index_start + self.ni * width
                indices = np.frombuffer(data, dtype=f'<u{width}', count=self.ni, offset=self.index_start)
                if len(indices) and int(indices.max()) >= self.nv:
                    continue
                groups = []
                expected_index = 0
                for _ in range(ng):
                    flag, first, base, count, vc, material = struct.unpack_from('<B5I', data, cursor)
                    if flag > 1 or first != expected_index or count % 3 or first + count > self.ni or base + vc > self.nv:
                        raise ValueError('Invalid material group')
                    groups.append(dict(offset=cursor, first=first, base=base, count=count, vertices=vc, material=material))
                    expected_index += count
                    cursor += 45
                if ng and expected_index != self.ni:
                    raise ValueError('Material groups do not cover triangles')
                sockets = []
                for _ in range(ns):
                    length, = struct.unpack_from('<I', data, cursor)
                    cursor += 4
                    if not 0 < length < 4096:
                        raise ValueError('Invalid socket name')
                    name = data[cursor:cursor+length].decode('utf8')
                    cursor += length
                    values = struct.unpack_from('<7f', data, cursor)
                    if not all(map(math.isfinite, values)):
                        raise ValueError('Non-finite socket')
                    sockets.append(dict(name=name, position=list(values[:3]), quaternion=list(values[3:]), offset=cursor))
                    cursor += 28
                if cursor == len(data):
                    candidates.append((width, indices.reshape(-1, 3).copy(), groups, sockets))
            except (ValueError, struct.error, UnicodeError):
                pass
        if len(candidates) != 1:
            raise ValueError(f'Ambiguous/unsupported INSM stream ({len(candidates)} valid layouts)')
        self.width, self.faces, self.groups, self.sockets = candidates[0]

    def attribute(self, slot):
        kind = {1: ('<f2', 2), 2: ('<f2', 4), 4: ('<f4', 2), 5: ('<f4', 3), 6: ('<f4', 4), 7: ('u1', 4)}
        if not self.sizes[slot]:
            return None
        if self.types[slot] not in kind:
            return None
        dtype, count = kind[self.types[slot]]
        size = np.dtype(dtype).itemsize * count
        if size != self.sizes[slot] or self.offsets[slot] + size > self.stride:
            raise ValueError('Unsupported attribute size')
        return np.ndarray((self.nv, count), dtype=dtype, buffer=self.data,
                          offset=260+self.offsets[slot], strides=(self.stride, np.dtype(dtype).itemsize)).astype(np.float32)

    def patch(self, positions=None, attributes=None, sockets=None):
        data = bytearray(self.data)
        attrs = dict(attributes or {})
        if positions is not None:
            attrs[1] = positions
        for slot, values in attrs.items():
            original = self.attribute(slot)
            values = np.asarray(values, dtype=np.float32)
            if original is None or original.shape != values.shape or not np.isfinite(values).all():
                raise ValueError(f'Unsupported edit to vertex attribute {slot}')
            dtype = '<f4' if self.types[slot] in (4, 5, 6) else '<f2' if self.types[slot] in (1, 2) else 'u1'
            target = np.ndarray(values.shape, dtype=dtype, buffer=data,
                                offset=260+self.offsets[slot], strides=(self.stride, np.dtype(dtype).itemsize))
            # Ignore float32 coordinate-conversion noise, not actual edits.
            changed = ~np.isclose(values, original, rtol=1e-6, atol=1e-9)
            converted = values.astype(dtype)
            if not np.isfinite(converted).all():
                raise ValueError('Edit exceeds vertex attribute precision')
            target[changed] = converted[changed]
        actual = np.ndarray((self.nv, 3), '<f4', buffer=data, offset=260, strides=(self.stride, 4))
        if not np.array_equal(actual, self.positions):
            struct.pack_into('<6d', data, 22, *actual.min(axis=0), *actual.max(axis=0))
            for group in self.groups:
                ids = self.faces.reshape(-1)[group['first']:group['first']+group['count']]
                if len(ids):
                    points = actual[ids]
                    struct.pack_into('<6f', data, group['offset']+21, *points.min(axis=0), *points.max(axis=0))
        for name, values in (sockets or {}).items():
            sock = next(s for s in self.sockets if s['name'] == name)
            values = np.asarray(values, dtype=np.float32)
            old = np.array(sock['position'] + sock['quaternion'])
            if values.shape != (7,) or not np.isfinite(values).all():
                raise ValueError('Invalid socket edit')
            if not np.allclose(old, values, rtol=1e-6, atol=1e-8):
                struct.pack_into('<7f', data, sock['offset'], *values)
        Mesh(data)  # Verify the rewritten stream before returning it.
        return bytes(data)

    def rebuild(self, positions, faces, attributes, material_slots):
        """Rebuild observed static layouts; keep declarations, material IDs and sockets.

        Each new vertex must supply every declared channel. Unknown channels are
        rejected, never populated with guessed bytes from an unrelated vertex.
        """
        positions = np.asarray(positions, dtype=np.float32)
        faces = np.asarray(faces)
        slots = np.asarray(material_slots)
        if positions.ndim != 2 or positions.shape[1] != 3 or not len(positions) or not np.isfinite(positions).all():
            raise ValueError('Replacement must contain finite 3D vertices')
        if faces.ndim != 2 or faces.shape[1] != 3 or not len(faces) or faces.dtype.kind not in 'iu' or faces.min() < 0 or faces.max() >= len(positions):
            raise ValueError('Replacement must contain valid triangle indices')
        if len(positions) > 2**32-1:
            raise ValueError('Replacement exceeds 32-bit vertex count')
        index_width = 4 if len(positions) > 65536 else self.width
        if slots.shape != (len(faces),) or slots.dtype.kind not in 'iu' or slots.min() < 0 or slots.max() >= max(1, len(self.groups)):
            raise ValueError('Replacement uses an unknown game material slot')
        if any(np.any(faces[:, a] == faces[:, b]) for a, b in ((0, 1), (1, 2), (0, 2))):
            raise ValueError('Replacement has repeated-index triangles')
        attrs = dict(attributes)
        attrs[1] = positions
        vertex_data = bytearray(len(positions) * self.stride)
        covered = set()
        for slot, size in enumerate(self.sizes):
            if not size:
                continue
            original = self.attribute(slot)
            if original is None or slot not in attrs:
                raise ValueError(f'Replacement missing/unsupported vertex channel {slot}')
            values = np.asarray(attrs[slot], dtype=np.float32)
            if values.shape != (len(positions), original.shape[1]) or not np.isfinite(values).all():
                raise ValueError(f'Invalid replacement channel {slot}')
            dtype = '<f4' if self.types[slot] in (4, 5, 6) else '<f2' if self.types[slot] in (1, 2) else 'u1'
            if dtype == 'u1' and ((values < 0).any() or (values > 255).any()):
                raise ValueError('Vertex color outside byte range')
            converted = values.astype(dtype)
            if not np.isfinite(converted).all():
                raise ValueError('Replacement exceeds attribute precision')
            target = np.ndarray(values.shape, dtype=dtype, buffer=vertex_data, offset=self.offsets[slot], strides=(self.stride, np.dtype(dtype).itemsize))
            target[:] = converted
            covered.update(range(self.offsets[slot], self.offsets[slot] + size))
        old_vertices = np.frombuffer(self.data, np.uint8, count=self.nv*self.stride, offset=260).reshape(self.nv, self.stride)
        for offset in set(range(self.stride)) - covered:
            if np.any(old_vertices[:, offset]):
                raise ValueError('Unknown nonzero vertex padding; replacement is unsafe')
        # Groups reference global vertex indices (not base-relative indices).
        ordered, groups, first = [], bytearray(), 0
        for slot, group in enumerate(self.groups):
            triangles = faces[slots == slot]
            if not len(triangles):
                # Retain slot numbering, including empty original material slots.
                base, count, low, high = 0, 0, np.zeros(3), np.zeros(3)
            else:
                ids = triangles.ravel()
                base, count = int(ids.min()), int(ids.max()-ids.min()+1)
                low, high = positions[ids].min(axis=0), positions[ids].max(axis=0)
            groups += struct.pack('<B5I6f', self.data[group['offset']], first, base, triangles.size, count, group['material'], *low, *high)
            ordered.append(triangles)
            first += triangles.size
        ordered_faces = np.concatenate(ordered) if self.groups else faces
        header = bytearray(self.data[:260])
        struct.pack_into('<2I', header, 6, len(positions), faces.size)
        struct.pack_into('<6d', header, 22, *positions.min(axis=0), *positions.max(axis=0))
        tail = self.data[self.index_start + self.ni*self.width + len(self.groups)*45:]
        result = bytes(header) + vertex_data + ordered_faces.astype(f'<u{index_width}').tobytes() + groups + tail
        Mesh(result)
        return result


def material_instance(data):
    if data[:6] != b'mati\x01\x00':
        raise ValueError('Unsupported material instance')
    parent, count = struct.unpack_from('<IH', data, 6)
    cursor = 12
    params = {}
    for _ in range(count):
        length, = struct.unpack_from('<I', data, cursor)
        cursor += 4
        if not 0 < length < 4096:
            raise ValueError('Invalid material parameter')
        name = data[cursor:cursor+length].decode('utf8')
        cursor += length
        desc = data[cursor:cursor+5]
        cursor += 5
        if desc[0:2] == b'\x03\x00':
            fmt, kind = '<I', 'texture'
        elif desc[0:2] == b'\x02\x07':
            fmt, kind = '<f', 'scalar'
        elif desc[0:2] == b'\x02\x02':
            fmt, kind = '<4f', 'vector'
        else:
            raise ValueError(f'Unsupported material parameter {name}: {desc.hex()}')
        if desc[2:] != b'\x00\x01\x00':
            raise ValueError('Unsupported material parameter array')
        value = struct.unpack_from(fmt, data, cursor)
        params[name] = dict(kind=kind, value=value[0] if len(value) == 1 else list(value), offset=cursor, fmt=fmt)
        cursor += struct.calcsize(fmt)
    if cursor != len(data):
        raise ValueError('Unrecognized material trailing data')
    return parent, params


def material_defaults(data):
    """Read recognized typed defaults; compiled shader execution is not ported."""
    params = {}
    for match in re.finditer(rb'(?:[STV]_|V4_|SP_|_inovae_tex2d_|Colour|Ao)[A-Za-z0-9_]*', data):
        start, end = match.span()
        raw = match.group().rstrip(b'\x00')
        end = start + len(raw)
        if start < 6 or struct.unpack_from('<I', data, start-4)[0] != len(raw):
            continue
        desc = data[start-6:start-4]
        if data[end:end+9] != b'\x00\x01\x02\x01\x00\x00\x00\x01\x00':
            continue
        fmt_kind = {b'\x03\x00': ('<I', 'texture', 9), b'\x02\x07': ('<f', 'scalar', 11), b'\x02\x02': ('<4f', 'vector', 11)}.get(desc)
        if fmt_kind:
            fmt, kind, skip = fmt_kind
            values = struct.unpack_from(fmt, data, end+skip)
            params[raw.decode()] = dict(kind=kind, value=values[0] if len(values) == 1 else list(values))
    return params


def texture_png(source, destination):
    from PIL import Image
    import io
    data = Path(source).read_bytes()
    if data[:4] != b'TXB1' or len(data) < 56:
        raise ValueError('Unsupported texture container')
    width, height, depth, arrays, cube, mips, dxgi = struct.unpack_from('<7I', data, 4)
    if depth not in (0, 1) or arrays != 1 or cube or not 0 < width <= 32768 or not 0 < height <= 32768:
        raise ValueError('Only 2D single-layer textures are supported')
    # TXB stores a contiguous mip chain at byte 56; DX10 DDS preserves its encoding.
    header = struct.pack('<7I11I8I5I', 124, 0x2100f, height, width, 0, 0, mips,
                         *([0]*11), 32, 4, int.from_bytes(b'DX10','little'), 0, 0, 0, 0, 0,
                         0x401008, 0, 0, 0, 0)
    # SRGB variants have identical encoded bytes; Pillow lacks some of their
    # enum aliases. Decode the UNORM twin without changing stored pixel values.
    decode_format = {29:28,72:71,75:74,78:77,91:87,99:98}.get(dxgi,dxgi)
    dds = b'DDS ' + header + struct.pack('<5I', decode_format, 3, 0, 1, 0) + data[56:]
    if dxgi == 31:  # R8G8B8A8_SNORM, mapped to displayable 0..1 for normal nodes.
        values = np.frombuffer(data,dtype=np.int8,count=width*height*4,offset=56).reshape(height,width,4)
        rgba = np.rint((np.maximum(values.astype(np.float32)/127,-1)*.5+.5)*255).astype(np.uint8)
        img = Image.fromarray(rgba)
    else:
        img = Image.open(io.BytesIO(dds)).convert('RGBA')
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    img.save(destination)
    return dict(width=width, height=height, dxgi=dxgi)
