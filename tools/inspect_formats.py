from pathlib import Path
import re
import struct
import zlib

root = Path('A:/Steam/steamapps/common/Infinity Battlescape/Dev')
name = 'Ships/SFC-Fighter/SM_SFC_Fighter_exterior_no_cockpit_Lod0'
known = {p.stem for p in (root / 'Ships/SFC-Fighter').glob('*.insm')}
def murmur(data, seed=0):
    h = seed
    for i in range(0, len(data)//4*4, 4):
        k = int.from_bytes(data[i:i+4], 'little') * 0xcc9e2d51 & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        k = k * 0x1b873593 & 0xffffffff
        h ^= k
        h = ((h << 13) | (h >> 19)) & 0xffffffff
        h = (h * 5 + 0xe6546b64) & 0xffffffff
    tail = data[len(data)//4*4:]
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

def murmur2(data, seed=0):
    h = seed ^ len(data)
    for i in range(0,len(data)//4*4,4):
        k = int.from_bytes(data[i:i+4],'little') * 0x5bd1e995 & 0xffffffff
        k ^= k >> 24
        k = k * 0x5bd1e995 & 0xffffffff
        h = (h * 0x5bd1e995) ^ k
        h &= 0xffffffff
    tail = data[len(data)//4*4:]
    if tail:
        h ^= int.from_bytes(tail,'little')
        h = h * 0x5bd1e995 & 0xffffffff
    h ^= h >> 13
    h = h * 0x5bd1e995 & 0xffffffff
    return h ^ (h >> 15)

for s in [name, name.lower(), name.upper(), name.rsplit('/',1)[-1],name.rsplit('/',1)[-1].lower()]:
    for prefix in ['', '$Dev/', 'Dev/']:
        for suffix in ['', '.insm', '\0']:
            for encoding in ['utf8', 'utf-16-le']:
                text = prefix + s + suffix
                b = text.encode(encoding)
                candidates = [('crc',zlib.crc32(b)),('crc_init',zlib.crc32(b,0xffffffff)),('murmur',murmur(b)),('murmur42',murmur(b,42))]
                candidates += [(f'murmur2_{seed}',murmur2(b,seed)) for seed in [0,1,42,0x9747b28c,0xdeadbeef]]
                h64=14695981039346656037
                for c in b: h64=((h64^c)*1099511628211)&0xffffffffffffffff
                candidates += [('fnv64low',h64&0xffffffff),('fnv64high',h64>>32),('fnv64xor',(h64^(h64>>32))&0xffffffff)]
                for seed in [0,5381,2166136261]:
                    for mul in [31,33,65599,16777619]:
                        for mode in [0,1,2]:
                            h=seed
                            for c in b:
                                h=((h*mul+c) if mode==0 else (h*mul)^c if mode==1 else (h^c)*mul)&0xffffffff
                            candidates.append((f'poly_{seed}_{mul}_{mode}',h))
                for algorithm, h in candidates:
                    if f'{h:08x}' in known:
                        print('FOUND', algorithm, repr(text), encoding, hex(h))
for text in [name, name.lower(), name.replace('/', '\\'), name.lower().replace('/', '\\')]:
    for seed in [0, 5381, 2166136261]:
        for mul in [31, 33, 65599, 16777619]:
            for mode in [0, 1, 2]:
                h = seed
                for c in text.encode():
                    h = ((h*mul+c) if mode == 0 else (h*mul)^c if mode == 1 else (h^c)*mul) & 0xffffffff
                if f'{h:08x}' in known:
                    print('HASH', text, seed, mul, mode, hex(h))
data = (root / 'DirectX11/Ships/SFC-Fighter/d819ce37.cmat').read_bytes()
print('CMAT', len(data), data[:400].hex(' '))
print(re.findall(rb'[ -~]{5,}', data)[:150])
for path in (root/'Ships/SFC-Fighter').glob('*.insm'):
    d = path.read_bytes()
    v, i, g, sockets = struct.unpack_from('<IIII', d, 6)
    stride = struct.unpack_from('<H', d, 254)[0]
    print(path.name, 'vertices', v, 'indices', i, 'groups', g, 'sockets', sockets, 'stride', stride, 'tail2/4', len(d)-260-v*stride-i*2, len(d)-260-v*stride-i*4)
