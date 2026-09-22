// Read-only interoperability check using the editor's envelope/layout.
import {readFileSync} from 'node:fs'
import {createDecipheriv} from 'node:crypto'
const b=readFileSync(process.argv[2])
if(b.subarray(0,4).toString()!=='IBE1') throw Error('Wrong envelope')
const d=createDecipheriv('aes-256-gcm',Buffer.from('18d361eac6d0c1c7368ffeed0a38dc90371dba273b30929c75bd2518db90d398','hex'),b.subarray(4,16))
d.setAuthTag(b.subarray(-16))
const plain=Buffer.concat([d.update(b.subarray(16,-16)),d.final()])
if(plain.subarray(0,4).toString()!=='IBS1') throw Error('Wrong plaintext')
const size=plain.readUInt32LE(4), pc=plain.readUInt32LE(8), ic=plain.readUInt32LE(12)
const meta=JSON.parse(plain.subarray(16,16+size))
const start=(16+size+3)&~3
if(start+4*(pc+ic)!==plain.length) throw Error('Length mismatch')
for(const m of meta.meshes) {
 if(m.positionOffset+m.positionCount>pc || m.indexOffset+m.indexCount>ic) throw Error('Invalid offsets')
 if('boundsMin' in m || 'sourceLevel' in m) throw Error('Unexpected bounds/LOD')
 for(let i=0;i<m.indexCount;i++) if(plain.readUInt32LE(start+pc*4+(m.indexOffset+i)*4)>=m.positionCount/3) throw Error('Invalid index')
}
for(const instances of Object.values(meta.assemblies)) for(const a of instances) if(a.length!==9 || !meta.meshes[a[0]]) throw Error('Invalid instance')
console.log('Node/editor-compatible AES-GCM + IBS1:',Object.keys(meta.assemblies).length,'actors,',meta.meshes.length,'meshes; no bounds/LOD payload')
