"""Mission Editor IBS1 geometry in its existing authenticated IBE1 envelope.

Full source collision/HitMesh only. No LOD search, shader or texture loading.
The editor already ships independent bounds-only JSON metadata.
"""
import json
import os
import struct
import hashlib
from pathlib import Path
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .formats import Assets, Mesh, xml_read
from .project import catalog, transform

KEY = bytes.fromhex('18d361eac6d0c1c7368ffeed0a38dc90371dba273b30929c75bd2518db90d398')


def encrypt(plain):
    nonce = os.urandom(12)
    return b'IBE1'+nonce+AESGCM(KEY).encrypt(nonce,plain,None)


def decrypt(data):
    if data[:4] != b'IBE1' or len(data)<32:
        raise ValueError('Invalid encrypted package')
    return AESGCM(KEY).decrypt(data[4:16],data[16:],None)


def rotation(q):
    w,x,y,z=np.asarray(q,dtype=float)/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def matrix(node):
    t=transform(node)
    result=np.eye(4)
    # Convert Blender Z-up transforms to the editor's right-handed Y-up frame.
    basis=np.array([[1,0,0],[0,0,1],[0,-1,0]])
    result[:3,:3]=basis@rotation(t['quaternion'])@np.diag(t['scale'])@basis.T
    result[:3,3]=basis@np.array(t['position'])/1000
    if not np.isfinite(result).all():
        raise ValueError('Non-finite assembly transform')
    return result


def quaternion(m):
    # Stable matrix-to-quaternion conversion, also at 180 degrees.
    values=np.array([1+m[0,0]-m[1,1]-m[2,2],1-m[0,0]+m[1,1]-m[2,2],
                     1-m[0,0]-m[1,1]+m[2,2],1+np.trace(m)])
    i=int(np.argmax(values))
    q=np.zeros(4)
    q[i]=np.sqrt(max(values[i],0))/2
    d=4*q[i]
    if i==3:
        q[:3]=[(m[2,1]-m[1,2])/d,(m[0,2]-m[2,0])/d,(m[1,0]-m[0,1])/d]
    else:
        j,k=(i+1)%3,(i+2)%3
        q[j]=(m[i,j]+m[j,i])/d
        q[k]=(m[i,k]+m[k,i])/d
        q[3]=(m[k,j]-m[j,k])/d
    q=q/np.linalg.norm(q)
    if q[3]<0: q=-q
    return q.tolist()


def encode(meshes,assemblies):
    metadata=[]
    pcount=icount=0
    for mesh in meshes:
        p,i=mesh['positions'],mesh['indices']
        metadata.append(dict(id=mesh['id'],component=mesh['component'],positionOffset=pcount,
                             positionCount=p.size,indexOffset=icount,indexCount=i.size))
        pcount+=p.size
        icount+=i.size
    meta=json.dumps(dict(version=1,meshes=metadata,assemblies=assemblies),separators=(',',':')).encode()
    return (struct.pack('<4sIII',b'IBS1',len(meta),pcount,icount)+meta+bytes((-len(meta))%4)
            +b''.join(m['positions'].astype('<f4').tobytes() for m in meshes)
            +b''.join(m['indices'].astype('<u4').tobytes() for m in meshes))


class CollisionCatalog:
    def __init__(self,assets,log=print):
        self.assets,self.log=assets,log
        self.meshes=[]
        self.by_path={}
        self.assemblies={}
        self.xml={}

    def add_mesh(self,path,source,world,instances):
        key=str(path).lower()
        if key not in self.by_path:
            raw=Mesh(path.read_bytes())
            points=raw.positions.copy()
            points[:,2]*=-1
            # Match the existing Mission Editor package winding convention.
            indices=raw.faces[:,[0,2,1]].copy()
            self.by_path[key]=len(self.meshes)
            self.meshes.append(dict(id=path.stem,component=self.assets.relative(source).removeprefix('Dev/'),
                                    positions=points,indices=indices))
        index=self.by_path[key]
        linear=world[:3,:3]
        if not np.isfinite(world).all(): raise ValueError('Non-finite collision transform')
        scale=float(np.linalg.norm(linear[:,0]))
        if scale<=0 or not np.allclose(linear.T@linear,np.eye(3)*scale*scale,rtol=1e-5,atol=1e-12) or np.linalg.det(linear)<=0:
            # IBS1 has one scalar per instance. Bake exceptional affine linear
            # transforms into a deduplicated mesh variant, retaining translation.
            token=hashlib.sha256(linear.astype('<f8').tobytes()).hexdigest()[:16]
            variant=key+'#'+token
            if variant not in self.by_path:
                base=self.meshes[index]
                points=base['positions']@linear.T
                faces=base['indices'].copy()
                if np.linalg.det(linear)<0: faces=faces[:,[0,2,1]]
                self.by_path[variant]=len(self.meshes)
                self.meshes.append(dict(id=base['id']+'-'+token,component=base['component'],positions=points,indices=faces))
            instances.append([self.by_path[variant],*world[:3,3].tolist(),0,0,0,1,1])
            return
        instances.append([index,*world[:3,3].tolist(),*quaternion(linear/scale),scale])

    def file(self,path,world,instances,stack=()):
        key=str(path).lower()
        if key in stack or len(stack)>48:
            raise ValueError('Cyclic/deep assembly link: '+str(path))
        if key not in self.xml:
            self.xml[key]=xml_read(path)
        root=self.xml[key]
        # Standalone actors use their explicit HitMesh, not internal cockpit
        # collision or lower render LODs. This matches the current packager.
        hit=root.find('./CBodyComponent/HitMesh')
        if hit is not None and hit.find('CollisionFile') is not None:
            self.walk(hit,path,world,instances,stack+(key,))
        else:
            self.walk(root,path,world,instances,stack+(key,))

    def walk(self,node,source,world,instances,stack):
        if not isinstance(node.tag,str): return
        if node.tag.startswith('CServer') or node.tag in ('CClientInternalCockpitComponent','CClientExternalCockpitComponent','LOD','Socket','ThrusterModel'):
            return
        if node.tag=='Condition' and node.get('Target','').lower()=='server': return
        if node.tag in ('Link','Object','TransformNode'):
            world=world@matrix(node)
        if node.tag=='Link':
            self.file(self.assets.path(node.attrib['Target']),world,instances,stack)
            return
        if node.tag in ('PhysicsBody','HitMesh','CockpitBody'):
            scale=float(node.findtext('CollisionScale','1'))
            world=world@np.diag([scale,scale,scale,1])
        if node.tag=='CollisionFile':
            self.add_mesh(self.assets.path(node.text or ''),source,world,instances)
            return
        for child in node:
            self.walk(child,source,world,instances,stack)

    def actor(self,ref):
        path=self.assets.path(ref)
        name=path.stem
        if name in self.assemblies: raise ValueError('Duplicate actor class name: '+name)
        instances=[]
        initial=len(self.meshes)
        try:
            self.file(path,np.eye(4),instances)
        except Exception:
            self.meshes=self.meshes[:initial]
            self.by_path={k:v for k,v in self.by_path.items() if v<initial}
            raise
        if not instances: raise ValueError('No explicit collision mesh: '+ref)
        self.assemblies[name]=instances
        self.log(f'{name}: {len(instances)} collision mesh instances')


def export_package(game,actors,destination,log=print):
    destination=Path(destination).resolve()
    if destination.suffix.lower()!='.ibmesh' or destination.exists():
        raise ValueError('Choose a NEW .ibmesh filename')
    assets=Assets(game)
    builder=CollisionCatalog(assets,log)
    auto_all=not actors
    if auto_all:
        # Prefer actor configs over same-named subordinate Nodes configs.
        rows=sorted(catalog(assets),key=lambda row:(len(Path(row['path']).parts),row['path']))
        unique={}
        for row in rows: unique.setdefault(row['name'],row['path'])
        actors=list(unique.values())
    skipped=[]
    for ref in actors:
        try:
            builder.actor(ref)
        except ValueError as e:
            if str(e).startswith('No explicit collision mesh:') and len(actors)>1:
                skipped.append(ref)
                log('Skipped (no explicit collision mesh): '+ref)
            else: raise
        except FileNotFoundError as e:
            if not auto_all: raise
            skipped.append(ref)
            log(f'Skipped incomplete game config {ref}: missing {e.filename}')
    if not builder.assemblies: raise ValueError('No collision geometry to package')
    data=encrypt(encode(builder.meshes,builder.assemblies))
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation: never overwrite a package or an editor asset.
    with destination.open('xb') as stream: stream.write(data)
    log(f'Saved {destination}: {len(builder.assemblies)} actors, {len(builder.meshes)} unique meshes; no LODs or bounding boxes.')
    return dict(actors=len(builder.assemblies),meshes=len(builder.meshes),skipped=skipped,bytes=len(data))
