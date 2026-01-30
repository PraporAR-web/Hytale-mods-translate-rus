# -*- coding: utf-8 -*-
"""
Конвертирует PNG-иконку в app.ico для exe и ярлыка.
Запускать перед сборкой: python make_icon.py
"""
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Установите Pillow: pip install Pillow")
    raise

ROOT = Path(__file__).resolve().parent
PNG_NAME = "Gemini_Generated_Image_myjg1qmyjg1qmyjg.png"
ICO_NAME = "app.ico"
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]


def main():
    png_path = ROOT / PNG_NAME
    if not png_path.exists():
        print(f"Файл не найден: {png_path}")
        print("Положите PNG-картинку в папку проекта и укажите имя в PNG_NAME в этом скрипте.")
        return 1
    img = Image.open(png_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGBA")
    else:
        img = img.convert("RGB")
    ico_path = ROOT / ICO_NAME
    img.save(ico_path, format="ICO", sizes=SIZES)
    print(f"Создан: {ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
