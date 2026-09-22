"""Lossless uncompressed TXB1 replacements, preserving sampler metadata.

BC inputs become RGBA8 UNORM/SRGB/SNORM. No lossy compression dependency or
compiled shader change is needed. Pixel input is top-to-bottom encoded RGBA.
"""
import struct
import numpy as np


def encode_texture(original, rgba):
    if original[:4] != b'TXB1' or len(original) < 56:
        raise ValueError('Unsupported texture container')
    width, height, depth, arrays, cube, mips, dxgi = struct.unpack_from('<7I', original, 4)
    if depth not in (0, 1) or arrays != 1 or cube or not mips:
        raise ValueError('Only 2D single-layer texture replacement is supported')
    srgb = dxgi in (29, 72, 75, 78, 91, 99)
    signed = dxgi in (31, 81, 84)
    if dxgi not in (28, 29, 31, 71, 72, 74, 75, 77, 78, 80, 81, 83, 84, 87, 91, 98, 99):
        raise ValueError(f'Texture format {dxgi} cannot yet be written back')
    pixels = np.asarray(rgba, dtype=np.float32)
    if pixels.ndim != 3 or pixels.shape[2] != 4 or min(pixels.shape[:2]) < 1 or max(pixels.shape[:2]) > 8192 or not np.isfinite(pixels).all():
        raise ValueError('Replacement must be finite RGBA, at most 8192 by 8192')
    if (pixels < 0).any() or (pixels > 1).any():
        raise ValueError('HDR/out-of-range texture pixels are unsupported')
    height, width = pixels.shape[:2]
    levels = 1 if mips == 1 else int(np.floor(np.log2(max(width, height)))) + 1
    payload = bytearray()
    for level in range(levels):
        values = np.rint((pixels*2-1)*127).astype(np.int8) if signed else np.rint(pixels*255).astype(np.uint8)
        payload += values.tobytes()
        if level+1 == levels:
            break
        h, w = pixels.shape[:2]
        nh, nw = max(1, h//2), max(1, w//2)
        linear = pixels.copy()
        if srgb:
            c = linear[:, :, :3]
            linear[:, :, :3] = np.where(c <= .04045, c/12.92, ((c+.055)/1.055)**2.4)
        # Area average includes the last row/column for non-power-of-two maps.
        rows = np.array([linear[(y*h)//nh:((y+1)*h)//nh].mean(axis=0) for y in range(nh)])
        pixels = np.stack([rows[:, (x*w)//nw:((x+1)*w)//nw].mean(axis=1) for x in range(nw)], axis=1)
        if srgb:
            c = pixels[:, :, :3]
            pixels[:, :, :3] = np.where(c <= .0031308, c*12.92, 1.055*c**(1/2.4)-.055)
    header = bytearray(original[:56])
    struct.pack_into('<2I', header, 4, width, height)
    struct.pack_into('<2I', header, 24, levels, 31 if signed else 29 if srgb else 28)
    struct.pack_into('<I', header, 52, len(payload))
    return bytes(header + payload)
