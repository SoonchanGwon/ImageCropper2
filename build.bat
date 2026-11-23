@echo off
REM Build ImageCropper.exe (output: dist\ImageCropper.exe)
cd /d "%~dp0"
python -m pip install -r requirements.txt || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name ImageCropper ^
  --icon icon.ico --add-data "icon.ico;." ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtPdf --exclude-module PySide6.Qt3DCore ^
  --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml --exclude-module tkinter ^
  image_cropper.py
