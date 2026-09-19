@echo off
REM Empaqueta la app como un .exe unico para Windows.
REM Ejecutar este archivo en una PC con Windows y Python instalado,
REM parado dentro de esta misma carpeta.
REM
REM IMPORTANTE - Windows 7: si la PC donde corre la app (no
REM necesariamente esta donde compilas) es Windows 7, este script debe
REM correrse con Python 3.8.10 instalado (la ultima version de Python
REM con soporte oficial para Windows 7 - versiones mas nuevas de Python
REM ya no arrancan en Windows 7) y usa requirements-win7.txt en vez de
REM requirements.txt, ademas de una version vieja de PyInstaller (las
REM versiones nuevas de PyInstaller ya no soportan Windows 7 tampoco).
REM Ver la seccion "Windows 7" del README.md para el detalle completo.
REM Si el negocio ya tiene Windows 8.1/10/11, ignora esto y usa la
REM opcion normal (Python y PyInstaller mas recientes).

python --version
echo.
echo Si la version de arriba NO es 3.8.x y la PC donde va a CORRER la
echo app es Windows 7, detente (Ctrl+C) y revisa el README.md primero.
echo.
pause

python -m venv .venv
call .venv\Scripts\activate.bat

echo.
echo Que version de Windows tiene la PC donde va a CORRER la app (no
echo necesariamente esta)?
echo   1 = Windows 7
echo   2 = Windows 8.1 / 10 / 11
set /p winver="Escribe 1 o 2 y presiona Enter: "

if "%winver%"=="1" (
    echo Instalando dependencias fijadas para Windows 7...
    pip install -r requirements-win7.txt
    pip install pyinstaller==4.10
) else (
    pip install -r requirements.txt
    pip install pyinstaller
)

pyinstaller --onefile --windowed --name "MezclillaPOS" app.py

REM La carpeta resources/ (el logo) NO va dentro del .exe: la app la
REM busca junto al .exe en tiempo de ejecucion. Se copia junto al
REM ejecutable final para que quede lista para entregar/copiar.
if exist resources (
    xcopy /E /I /Y resources dist\resources >nul
)

echo.
echo Listo. El ejecutable queda en dist\MezclillaPOS.exe junto con la
echo carpeta dist\resources (el logo). Para instalarlo en otra PC copia
echo TODA la carpeta dist (el .exe y resources juntos, en la misma
echo carpeta) - no requiere tener Python instalado en esa PC.
echo.
echo Si compilaste para Windows 7, pruebalo primero en la PC de
echo Windows 7 real antes de darlo por bueno (ver README.md).
pause
