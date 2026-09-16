@echo off
REM Construye el ejecutable de Windows de AstroPhysics Suite (Fase 9).
REM Ejecutar desde una consola de Windows (cmd), con la raiz del repositorio
REM como directorio de trabajo o desde cualquier sitio -- el script resuelve
REM las rutas relativas a si mismo.
REM
REM Requisitos: Python 3.11+ instalado y en PATH.

setlocal
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
set VENV_DIR=%PROJECT_ROOT%\.venv-build

echo [1/5] Creando entorno virtual de build en %VENV_DIR% ...
python -m venv "%VENV_DIR%"
if errorlevel 1 goto :error

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 goto :error

echo [2/5] Instalando dependencias de la aplicacion (requirements-app.txt) ...
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r "%PROJECT_ROOT%\requirements-app.txt"
if errorlevel 1 goto :error

echo [3/5] Instalando PyInstaller (requirements-build.txt) ...
python -m pip install -r "%PROJECT_ROOT%\requirements-build.txt"
if errorlevel 1 goto :error

echo [4/5] Limpiando builds anteriores ...
if exist "%PROJECT_ROOT%\build" rmdir /s /q "%PROJECT_ROOT%\build"
if exist "%PROJECT_ROOT%\dist" rmdir /s /q "%PROJECT_ROOT%\dist"

echo [5/5] Empaquetando con PyInstaller ...
cd /d "%PROJECT_ROOT%"
pyinstaller packaging\AstroPhysicsSuite.spec --noconfirm
if errorlevel 1 goto :error

echo.
echo Build completado: %PROJECT_ROOT%\dist\AstroPhysicsSuite\AstroPhysicsSuite.exe
echo Para construir el instalador, compila packaging\installer.iss con Inno Setup
echo (https://jrsoftware.org/isinfo.php) una vez este build haya terminado.
goto :eof

:error
echo.
echo El build fallo -- revisa el mensaje de arriba.
exit /b 1
