@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
echo Instalacion completada. Ejecuta INICIAR_WINDOWS.cmd
pause
exit /b 0
:error
echo No se completo la instalacion. Revisa el mensaje anterior y que Python 3.12 este instalado.
pause
exit /b 1
