exec(open('ActorWorkbench/tools/inspect_hash.py').read().split('for value')[0])
targets={0x2b23f0,0x2b23d0,0x2b2350,0x812aa0}
for offset in range(len(d)-5):
    if d[offset]!=0xe8: continue
    section=pe.get_section_by_offset(offset)
    if section is None or not section.Name.startswith(b'.text'): continue
    rva=pe.get_rva_from_offset(offset)
    target=rva+5+struct.unpack_from('<i',d,offset+1)[0]
    if target not in targets: continue
    fn=next((e.struct for e in pe.DIRECTORY_ENTRY_EXCEPTION if e.struct.BeginAddress<=rva<e.struct.EndAddress),None)
    print('CALL',hex(rva),hex(target),hex(fn.BeginAddress) if fn else '')
    if fn:
        start=pe.get_offset_from_rva(fn.BeginAddress)
        ins=list(cs.disasm(d[start:offset+7],0x140000000+fn.BeginAddress))
        print('\n'.join(f'{i.address:x} {i.mnemonic} {i.op_str}' for i in ins[-24:]))
