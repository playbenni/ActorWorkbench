from pathlib import Path
from PIL import Image
import sys
Image.MAX_IMAGE_PIXELS = None
source = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1] / 'samples/skin.png'
with Image.open(source) as image:
    print(image.size, image.mode)
    image.thumbnail((1024,1024))
    image.save(source.with_name(source.stem+'-thumbnail.png'))
