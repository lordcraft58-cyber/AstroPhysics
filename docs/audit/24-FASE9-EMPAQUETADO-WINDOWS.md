# AstroPhysics Suite — Fase 9: empaquetado comercial de Windows

Tarea pendiente desde el inicio del proyecto (nunca programada dentro del
orden de prioridad de los seis bloques científicos -- CCDRED, análisis de
imagen, fotometría, astrometría, tablas/catálogos, espectroscopía -- por
ser de una naturaleza distinta: empaquetado, no capacidad científica).
Con los seis bloques cerrados (Fases 10-18), esta fase entrega la
infraestructura real de construcción del ejecutable e instalador de
Windows del taller (`qt_app/`), documentada en detalle en
`packaging/README.md`.

## 1. Qué se construyó

- `packaging/entrypoint.py` -- punto de entrada real para PyInstaller
  (`Analysis` exige un script, no admite `python -m qt_app`), sin duplicar
  lógica: llama directamente a `qt_app.__main__.main`.
- `packaging/AstroPhysicsSuite.spec` -- especificación de PyInstaller en
  modo `onedir` (justificado en el README: arranque casi instantáneo
  frente a los varios segundos de `onefile` al descomprimir astropy/
  matplotlib/Qt en cada arranque), con `collect_all` explícito para
  astropy/photutils/astroquery/matplotlib/scipy (paquetes con datos
  propios que el análisis estático no siempre descubre completo) y
  `tkinter` excluido a propósito (`gui/`, Fase 8, es solo referencia de
  diseño).
- `packaging/version_info.txt` -- metadatos de versión de Windows
  (Propiedades → Detalles del .exe).
- `packaging/build_windows.bat` -- automatiza entorno virtual + instalación
  de dependencias + build, pensado para `cmd` de Windows.
- `packaging/installer.iss` -- script de Inno Setup: instalador con acceso
  directo de menú inicio, icono de escritorio opcional y desinstalador.
- `requirements-app.txt` -- manifiesto de dependencias del producto
  (auditado contra imports reales en `legacy/
  AstroPhysicsSuite_v57_3_COMMERCIAL.py`: numpy/scipy/astropy/photutils/
  matplotlib/openpyxl/astroquery/PySide6 -- todos genuinamente necesarios
  en tiempo de ejecución, no solo en tests). `scikit-image`/
  `scikit-learn` quedan fuera deliberadamente: son comprobados de forma
  opcional por el propio código heredado (`HAS_SKIMAGE`/`HAS_SKLEARN`,
  con `ImportError` manejado explícitamente) y ninguna capacidad ya
  cableada de la GUI los necesita.
- `requirements-build.txt` -- `pyinstaller`, separado del manifiesto de la
  app (nunca se instala en el producto final).

## 2. Verificación real (y su límite honesto)

Este contenedor de desarrollo corre Linux -- PyInstaller no hace
compilación cruzada, así que no se pudo producir ni probar un `.exe` de
Windows real aquí. Lo que sí se verificó, de extremo a extremo, no
simulado:

- `pyinstaller packaging/AstroPhysicsSuite.spec` completó un build
  **Linux** sin errores, resolviendo con éxito los hidden imports de los
  cinco paquetes científicos vía la misma lógica de `Analysis` que
  correrá en Windows.
- El ejecutable Linux resultante (491 MB, modo `onedir`) se lanzó de
  verdad bajo Xvfb y permaneció corriendo sin excepción ni traceback --
  la ventana principal del taller arrancó correctamente empaquetada.

Queda pendiente, y documentado explícitamente como tal en
`packaging/README.md` (no oculto): un primer build real en una máquina
Windows, que es la única verificación que de verdad certifica que
`AstroPhysicsSuite.exe` funciona para un usuario final, y la compilación
de `installer.iss` con Inno Setup (herramienta de Windows, no disponible
en este contenedor).

## 3. Qué queda fuera de esta fase, deliberadamente

- **Icono propio**: no existe un `.ico` del proyecto -- diseñarlo es una
  tarea gráfica independiente del empaquetado. `icon=None` usa el icono
  por defecto de PyInstaller; añadir uno real es un cambio de una línea
  en `AstroPhysicsSuite.spec` e `installer.iss` cuando exista.
- **Firma de código**: el instalador y el ejecutable no están firmados
  (requeriría un certificado de firma de código, un coste/proceso
  comercial fuera del alcance de esta fase de infraestructura).
- **Actualizaciones automáticas**: no implementadas -- cada nueva versión
  se distribuye como un instalador nuevo.

Ninguno de los tres bloquea tener un instalador de Windows funcional; se
documentan aquí para que no queden implícitos.
