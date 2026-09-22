// Convert an existing bounds-only catalog to auditable editor metadata.
// Deliberately whitelist fields: no vertex/index buffers can reach the output.
import { readFileSync, writeFileSync } from 'node:fs'
import { createDecipheriv } from 'node:crypto'

const [source, destination] = process.argv.slice(2)
if (!source || !destination) throw new Error('Usage: node export_bounds_only.mjs bounds.ibmesh output.json')
const encrypted = readFileSync(source)
if (encrypted.subarray(0, 4).toString() !== 'IBE1') throw new Error('Expected encrypted bounds catalog')
const key = Buffer.from('18d361eac6d0c1c7368ffeed0a38dc90371dba273b30929c75bd2518db90d398', 'hex')
const cipher = createDecipheriv('aes-256-gcm', key, encrypted.subarray(4, 16))
cipher.setAuthTag(encrypted.subarray(-16))
const plain = Buffer.concat([cipher.update(encrypted.subarray(16, -16)), cipher.final()])
if (plain.subarray(0, 4).toString() !== 'IBB1' || plain.readUInt32LE(4) + 8 !== plain.length) throw new Error('Expected bounds only, not a geometry package')
const input = JSON.parse(plain.subarray(8).toString())
const vector = (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite)
const meshes = input.meshes.map(({ id, component, boundsMin, boundsMax }) => {
  if (typeof id !== 'string' || typeof component !== 'string' || !vector(boundsMin) || !vector(boundsMax) || boundsMin.some((v, axis) => v > boundsMax[axis])) throw new Error('Invalid bounds')
  return { id, component, boundsMin, boundsMax }
})
const assemblies = Object.fromEntries(Object.entries(input.assemblies).map(([name, instances]) => [name, instances.map((instance) => {
  if (!Array.isArray(instance) || ![8, 9].includes(instance.length) || !instance.every(Number.isFinite) || !Number.isInteger(instance[0]) || !meshes[instance[0]]) throw new Error('Invalid transform')
  return instance
})]))
writeFileSync(destination, JSON.stringify({ version: 1, meshes, assemblies }) + '\n')
console.log(`Exported bounds only: ${meshes.length} boxes, ${Object.keys(assemblies).length} assemblies`)
