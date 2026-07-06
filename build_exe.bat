@echo off
REM Build TYLT into a single self-contained exe (dist\TYLT.exe).
REM Requires: pip install -r requirements.txt pyinstaller

python make_icon.py
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name TYLT --icon icon.ico ^
  --add-data "icon.ico;." ^
  --collect-all deep_translator ^
  --collect-all uiautomation ^
  --collect-all comtypes ^
  main.py

echo.
echo Done. Output: dist\TYLT.exe
