# Сборка приложения в exe

1. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```

2. Иконка: положите PNG-картинку `Gemini_Generated_Image_myjg1qmyjg1qmyjg.png` в папку проекта и создайте .ico:
   ```bash
   python make_icon.py
   ```
   (получится `app.ico` — он подставится в exe и в ярлык)

3. Соберите один exe-файл:
   ```bash
   python -m PyInstaller build.spec
   ```
   (модуль называется PyInstaller с заглавными буквами; если не найден — сначала: `python -m pip install pyinstaller`)

4. Готовый файл: `dist/HytaleModsTranslator.exe`. Папку `dist` можно копировать на любой ПК с Windows.
