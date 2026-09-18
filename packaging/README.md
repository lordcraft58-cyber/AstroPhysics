# Empaquetado comercial de Windows (Fase 9)

Esta carpeta construye el ejecutable y el instalador de Windows de
AstroPhysics Suite a partir de `qt_app/` (el taller de procesamiento,
interfaz final del producto -- ver `README.md` de la raíz). No empaqueta
`gui/` (la GUI en Tkinter de la Fase 8, conservada solo como referencia de
diseño).

## Piezas

| Archivo | Qué hace |
|---|---|
| `entrypoint.py` | Punto de entrada real para PyInstaller (llama a `qt_app.__main__.main`, sin duplicar lógica) -- `Analysis` necesita un script, no admite `python -m qt_app`. |
| `AstroPhysicsSuite.spec` | Especificación de PyInstaller: qué empaquetar, qué excluir, modo onedir. |
| `version_info.txt` | Metadatos de versión de Windows (los que se ven en "Propiedades → Detalles" del .exe). |
| `build_windows.bat` | Crea un entorno virtual de build, instala dependencias y ejecuta PyInstaller -- pensado para correr en `cmd` de Windows. |
| `installer.iss` | Script de [Inno Setup](https://jrsoftware.org/isinfo.php) que empaqueta el resultado de PyInstaller en un instalador `.exe` con acceso directo, desinstalador y (opcional) icono de escritorio. |
| `../requirements-app.txt` | Manifiesto de dependencias del producto (sin `pytest`) -- lo que se instala antes de construir. |
| `../requirements-build.txt` | Solo `pyinstaller`, aparte del manifiesto de la app. |

## Cómo construir (en Windows)

1. Instala Python 3.11+ (marca "Add to PATH" en el instalador oficial de
   python.org).
2. Desde la raíz del repositorio, en `cmd`:
   ```
   packaging\build_windows.bat
   ```
   Esto crea `.venv-build\`, instala `requirements-app.txt` +
   `requirements-build.txt`, y deja el resultado en
   `dist\AstroPhysicsSuite\AstroPhysicsSuite.exe`.
3. Verifica manualmente que `dist\AstroPhysicsSuite\AstroPhysicsSuite.exe`
   arranca y abre el taller (cargar un FITS de prueba, ejecutar algún
   proceso) -- PyInstaller empaqueta correctamente en la inmensa mayoría de
   los casos, pero un build real en la máquina de destino es la única
   verificación que de verdad importa para un ejecutable de Windows.
4. Instala [Inno Setup](https://jrsoftware.org/isinfo.php) (gratuito) y
   compila `packaging\installer.iss` (clic derecho → "Compile", o
   `ISCC.exe packaging\installer.iss` desde la consola). El instalador
   queda en `packaging\output\AstroPhysicsSuite-0.5.0-Setup.exe`.

## Decisiones de diseño

**Modo `onedir`, no `onefile`.** PyInstaller puede producir un único
`.exe` autoextraíble o una carpeta con el ejecutable más sus
dependencias. Se eligió `onedir` deliberadamente: `onefile` descomprime
toda la pila científica (astropy trae tablas IERS/CDS, matplotlib trae
tipos de letra, PySide6 trae Qt completo) a una carpeta temporal en
**cada arranque**, lo que hace que abrir la aplicación tarde varios
segundos más cada vez -- inaceptable para una herramienta de uso diario.
`onedir` arranca casi instantáneamente y además es mucho más fácil de
depurar (se puede inspeccionar `dist\AstroPhysicsSuite\_internal\` para
ver qué se empaquetó de verdad). El instalador de Inno Setup oculta esta
decisión al usuario final -- para quien instala, sigue siendo "un .exe,
un instalador, un acceso directo".

**`tkinter` excluido explícitamente.** `gui/` (Fase 8) se conserva en el
repositorio como referencia de diseño, pero `qt_app/` es la interfaz
final -- no tiene sentido empaquetar dos GUIs completas en el producto
comercial.

**`collect_all` para astropy/photutils/astroquery/matplotlib/scipy.**
Estos paquetes traen datos propios (tablas, tipos de letra, extensiones
binarias) que el análisis estático de PyInstaller no siempre descubre
completo solo con los hooks incluidos -- se piden explícitamente en vez
de confiar en que baste. `scikit-image`/`scikit-learn` (comprobados de
forma opcional por `legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py` vía
`HAS_SKIMAGE`/`HAS_SKLEARN`, con manejo explícito de `ImportError`) se
dejan fuera deliberadamente -- no están en `requirements-app.txt` porque
ninguna capacidad ya cableada de la GUI los necesita.

**Icono.** Todavía no existe un `.ico` del proyecto -- `icon=None` en el
`.spec` usa el icono por defecto de PyInstaller. Añadir uno propio es
una tarea de diseño gráfico independiente, no de empaquetado; cuando
exista un `.ico` real, basta con pasar su ruta a `icon=` en
`AstroPhysicsSuite.spec` y a `SetupIconFile=` en `installer.iss`. No se
inventa un icono provisional para no fingir un acabado visual que
todavía no se ha decidido.

**Versión.** `APP_VERSION` en `AstroPhysicsSuite.spec`,
`FileVersion`/`ProductVersion` en `version_info.txt`, y
`MyAppVersion` en `installer.iss` se mantienen a mano en sincronía con
`PIPELINE_VERSION` de `qt_app/main_window.py` -- documentado aquí en vez
de automatizado para no acoplar el `.spec` a importar el árbol completo
de la aplicación durante el análisis de PyInstaller.

## Qué se verificó en esta fase (y qué no)

Este contenedor de desarrollo corre Linux, no Windows -- PyInstaller no
hace compilación cruzada (construye para la plataforma donde se ejecuta).
Lo que sí se verificó aquí, de verdad, no solo "el .spec no da error de
sintaxis":

- `pyinstaller packaging/AstroPhysicsSuite.spec` completó un build
  **Linux** de extremo a extremo sin errores, resolviendo con éxito los
  hidden imports de astropy/photutils/astroquery/matplotlib/scipy/PySide6
  vía la misma lógica de `Analysis` que se usará en el build de Windows.
- El ejecutable Linux resultante se lanzó de verdad (bajo Xvfb) y
  permaneció corriendo sin excepción ni traceback -- la ventana principal
  arrancó correctamente empaquetada, no solo "el intérprete no crasheó".

El build emitió un aviso benigno conocido, documentado aquí en vez de
ocultado: `WARNING: Hidden import "scipy.special._cdflib" not found!` --
un submódulo interno de scipy que el hook de PyInstaller busca de forma
optimista mientras no todas las versiones de scipy lo traen; el
lanzamiento real del ejecutable (que sí ejercita `scipy.optimize` a fondo
en el resto de la suite de tests) no mostró ningún fallo relacionado.

Lo que **no** se pudo verificar aquí, y necesita una máquina Windows real
antes de distribuir el instalador: que `AstroPhysicsSuite.exe` arranca en
Windows (los hooks de PyInstaller para Windows -- DLLs de VC++ runtime,
`user32`/`gdi32`, etc. -- son distintos de los de Linux, ya avisado en el
build de prueba con `WARNING: Library user32 required via ctypes not
found`, esperado y benigno al construir fuera de Windows); y que
`installer.iss` compila y produce un instalador funcional (Inno Setup es
una herramienta de Windows, no está disponible en este contenedor). El
primer build real en una máquina Windows es, por tanto, el paso de
verificación pendiente antes de considerar el empaquetado "cerrado" en el
mismo sentido que el resto de fases de este documento -- motor y
configuración reales, verificación parcial honesta, no fingida.
