import struct
import zlib
import sys
import os

def make_png(w, h, r, g, b):
    def chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xffffffff
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', crc)
    raw = b''.join(b'\x00' + bytes([r, g, b] * w) for _ in range(h))
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', ihdr) +
            chunk(b'IDAT', zlib.compress(raw)) +
            chunk(b'IEND', b''))

sizes = {
    'mdpi': 48, 'hdpi': 72, 'xhdpi': 96,
    'xxhdpi': 144, 'xxxhdpi': 192
}

for density, size in sizes.items():
    folder = f'res/mipmap-{density}'
    os.makedirs(folder, exist_ok=True)
    path = f'{folder}/ic_launcher.png'
    with open(path, 'wb') as f:
        f.write(make_png(size, size, 26, 58, 107))
    print(f'Criado: {path} ({size}x{size})')
