import pefile
import capstone
from pathlib import Path
import struct

p=Path('A:/Steam/steamapps/common/Infinity Battlescape/Bin/Infinity Battlescape.exe')
d=p.read_bytes()
pe=pefile.PE(data=d)
cs=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
for value in [0x811c9dc5,0x01000193,0x5bd1e995,0xcc9e2d51,0x9747b28c,0xedb88320,0x82f63b78,0x9e3779b9]:
    pattern=struct.pack('<I',value)
    pos=0; found=[]
    while (pos:=d.find(pattern,pos))>=0:
        if pe.get_section_by_offset(pos) and pe.get_section_by_offset(pos).Name.startswith(b'.text'): found.append(pos)
        pos+=4
    print(hex(value), [hex(f) for f in found[:25]])
    for offset in found[:2]:
        start=offset-30
        print('\n'.join(f'{ins.address:x} {ins.mnemonic} {ins.op_str}' for ins in cs.disasm(d[start:offset+100],pe.OPTIONAL_HEADER.ImageBase+pe.get_rva_from_offset(start))))
