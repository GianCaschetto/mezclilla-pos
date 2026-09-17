@echo off
REM Empaqueta la app como un .exe unico para Windows.
REM Ejecutar este archivo en una PC con Windows y Python instalado,
REM parado dentro de esta misma carpeta.

python -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt
pip install pyinstaller

pyinstaller --onefile --windowed --name "MezclillaPOS" app.py

echo.
echo Listo. El ejecutable queda en dist\MezclillaPOS.exe
echo Puedes copiar ese archivo .exe a cualquier PC con Windows,
echo no requiere tener Python instalado.
pause
