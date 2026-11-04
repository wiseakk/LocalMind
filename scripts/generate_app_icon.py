"""Rebuild the first-party waveform app icon (Pillow is a core dependency)."""
from pathlib import Path
from PIL import Image, ImageDraw


def main():
    assets = Path(__file__).resolve().parents[1] / 'static/assets'
    scale = 4
    image = Image.new('RGBA', (256 * scale, 256 * scale))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8 * scale, 8 * scale, 248 * scale, 248 * scale),
                           radius=58 * scale, fill='#5565d9')
    # Existing LocalMind waveform vocabulary; recognizable at taskbar size.
    for x, height in ((64, 48), (96, 96), (128, 144), (160, 96), (192, 48)):
        draw.rounded_rectangle(((x - 7) * scale, (128 - height // 2) * scale,
                                (x + 7) * scale, (128 + height // 2) * scale),
                               radius=7 * scale, fill='white')
    image = image.resize((256, 256), Image.Resampling.LANCZOS)
    image.save(assets / 'localmind.png')
    image.save(assets / 'localmind.ico', sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])


if __name__ == '__main__':
    main()
