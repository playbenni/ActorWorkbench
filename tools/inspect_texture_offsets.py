from pathlib import Path
import sys,struct,io
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ibworkbench.formats import Assets
from PIL import Image,ImageDraw
a=Assets('A:/Steam/steamapps/common/Infinity Battlescape')
d=a.resolve(0x4230956f,'.txb').read_bytes()
w,h=struct.unpack_from('<2I',d,4)
header=struct.pack('<7I11I8I5I',124,0x2100f,h,w,0,0,1,*([0]*11),32,4,int.from_bytes(b'DX10','little'),0,0,0,0,0,0x401008,0,0,0,0)
sheet=Image.new('RGB',(1200,800))
draw=ImageDraw.Draw(sheet)
for i,(offset,fmt) in enumerate([(56,99),(56,77),(56,83),(56,71),(52,99),(60,99),(64,99),(72,99)]):
    dds=b'DDS '+header+struct.pack('<5I',fmt,3,0,1,0)+d[offset:]+bytes(64)
    im=Image.open(io.BytesIO(dds)).convert('RGB')
    im.thumbnail((300,365))
    x,y=(i%4)*300,(i//4)*400
    sheet.paste(im,(x,y+25))
    draw.text((x+5,y+5),str((offset,fmt)),fill='white')
sheet.save(Path(__file__).resolve().parents[1]/'samples/texture-offset-diagnostic.jpg')
(Path(__file__).resolve().parents[1]/'samples/skin-decoder-test.dds').write_bytes(b'DDS '+header+struct.pack('<5I',99,3,0,1,0)+d[56:])
print('TXB',len(d),'header',d[:64].hex(' '))
