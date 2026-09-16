# AstroPhysics Suite — Fase 9.6: taller de procesamiento PixInsight/Qt (`qt_app/`)

Continuación de `11-FASE9-IRAF-PIXINSIGHT-PLAN.md`. Las oleadas 9.1-9.5 construyeron
el núcleo científico IRAF propio (`imtools`, `reduction`, `photometry.aperture`/`psf`,
`astrometry`, `spectroscopy`) sin ninguna interfaz. Esta oleada construye la interfaz
que el encargo pidió explícitamente: un taller inspirado en la arquitectura y estética
de PixInsight, sobre PySide6/Qt, que sustituye a la GUI en Tkinter de la Fase 8
(conservada como referencia en `docs/audit/10-FASE8-GUI.md`).

## 1. Arquitectura

```
qt_app/
├── theme.py                 # paleta oscura de baja saturación + QSS
├── main_window.py           # QMainWindow: MDI + docks + menús, orquestación
├── workers.py                # QThread + señales -- ningún proceso pesado en el hilo de GUI
├── mdi/
│   ├── stf.py                 # STF (auto-estiramiento) -- matemática pura, sin Qt
│   └── image_window.py         # QGraphicsView: zoom dinámico + soltar iconos de proceso
├── docks/
│   ├── process_explorer.py      # árbol categorizado, arrastrable
│   ├── properties_dock.py        # formulario de parámetros generado dinámicamente
│   └── console_dock.py            # consola conectada al `logging` estándar de Python
└── processes/
    ├── base.py                    # ProcessDefinition/ParameterSpec/ProcessResult
    └── registry.py                  # catálogo de procesos, adaptadores finos hacia astrophysics_suite/*
```

Misma disciplina de capas que el resto del proyecto: `qt_app/` es el único paquete con
permiso de importar Qt; nunca reimplementa un algoritmo, solo adapta parámetros de un
formulario a la firma real de una función de `astrophysics_suite.*` y traduce el
resultado de vuelta a lo que la vista necesita mostrar.

## 2. Lo que pedía el encargo, punto por punto

- **Tema oscuro de baja saturación** (`theme.py`): paleta propia, no copiada de
  PixInsight, pensada para el mismo objetivo (minimizar fatiga visual en sesiones
  largas de reducción).
- **Explorador de procesos**: `docks/process_explorer.py`, árbol categorizado
  (Reducción CCD, Utilidades de imagen, Fotometría, Espectroscopía, Astrometría).
- **Iconos de proceso arrastrables sobre una vista**: soltar un proceso del
  explorador sobre una ventana de imagen (`ImageView.dropEvent`) la selecciona como
  destino y abre sus parámetros en el panel de propiedades -- nunca ejecuta nada por
  sí solo; `Aplicar` es la única acción que dispara una ejecución real.
- **Espacio de trabajo MDI**: `QMdiArea`, ventanas de imagen flotantes/maximizables.
- **STF no destructivo**: `mdi/stf.py` -- función de transferencia de tonos medios
  (MTF) + punto de corte de sombras por estadística robusta (mediana + MAD),
  reimplementada desde la definición matemática, nunca toca el array científico
  subyacente (`ImageView.data` no cambia nunca; solo se deriva de él, bajo demanda,
  un buffer de 8 bits para pantalla).
- **Lupa/zoom dinámico**: rueda del ratón sobre `ImageView` (`QGraphicsView.scale`).
- **Consola integrada**: `docks/console_dock.py`, conectada al `logging` estándar de
  Python vía un `Handler` que emite por señal Qt (segura entre hilos) -- cualquier
  `logging.getLogger(...).info(...)` del resto del taller aparece ahí en tiempo real.

## 3. Procesos cableados en esta oleada (reales, no simulados)

- **Corrección de overscan** (`reduction.overscan`).
- **Rayos cósmicos, L.A.Cosmic** (`imtools.cosmic_rays`).
- **Fotometría de apertura en el centro** (`photometry.aperture`) -- proceso de
  medición puro: no produce una imagen nueva, informa flujo/magnitud/S-N en la
  consola. Nota declarada explícitamente en su descripción: usa un modelo de ruido
  Poisson aproximado (sin ganancia/lectura reales) mientras el taller no importa la
  incertidumbre real de calibración -- honestidad epistémica, no un dato inventado.
- **Ajuste de continuo sobre la fila central** (`spectroscopy.continuum`) --
  demostración de la firma real del motor tratando una fila de la imagen como
  espectro 1D.

El resto del catálogo (bias/dark/flat maestros, aritmética de dos imágenes, PSF/
daophot, traza espectral completa, calibración en longitud de onda, ajuste de WCS,
registro entre imágenes) aparece listado en el explorador -- para que la cobertura
completa de IRAF sea visible desde ya -- pero sin `run` todavía
(`ProcessDefinition.is_wired == False`, mostrado en gris con "(pendiente)" en el
árbol): cada uno necesita una interacción que el taller no tiene todavía (cargar
varios fotogramas a la vez, seleccionar posiciones sobre la imagen, una segunda
imagen de referencia). Se documenta como pendiente en vez de simular una ejecución
falsa -- la misma disciplina de honestidad epistémica que gobierna todo el proyecto,
aplicada aquí a la interfaz.

## 4. Verificación

Instalado `PySide6` (más las bibliotecas de sistema `libegl1`, `libxcb-cursor0`,
`libxkbcommon-x11-0`, `libxcb-icccm4`, `libxcb-keysyms1`, `libxcb-shape0`,
`libxcb-xkb1` -- necesarias para que Qt inicialice su backend `xcb`, ausentes en el
entorno base). Verificado bajo Xvfb con capturas de pantalla reales (no solo
`import`): ventana vacía, imagen sintética cargada con STF aplicado, proceso
seleccionado con su formulario, rayos cósmicos ejecutados de extremo a extremo
(nueva ventana con el píxel inyectado limpiado), y fotometría de apertura ejecutada
sin crear ventana nueva. Dos defectos reales encontrados y corregidos en el proceso:

- `QMdiArea` no toma su color de fondo de la hoja de estilos QSS (a diferencia de
  casi todo lo demás) -- se quedaba con el gris por defecto de Qt en medio de un tema
  oscuro. Corregido fijándolo por `QPalette`/`QBrush`, el mecanismo que sí respeta.
- La consola dependía de que `__main__.py` llamara a `logging.basicConfig` para que
  los mensajes `INFO` no se descartaran en el propio logger (su nivel por defecto es
  `WARNING`) antes de llegar a ningún *handler* -- silenciosa y frágil ante cualquier
  otro punto de entrada. Corregido: `ConsoleDock` baja el nivel del logger raíz a
  `INFO` por sí sola si nadie lo hizo ya (sin subir uno más verboso que alguien haya
  pedido explícitamente).

8 tests de humo nuevos en `tests/gui_smoke/test_qt_app_smoke.py` (construcción de la
ventana, carga de imagen, ejecución completa de un proceso con hilo de fondo real
incluido, verificación de que el píxel de rayo cósmico inyectado se limpia, que un
proceso de medición no crea ventana, que ejecutar sin imagen activa no lanza
excepción, que soltar un proceso sobre una vista la selecciona, y que alternar STF no
lanza excepción). Además, 28 tests nuevos de lógica pura sin Qt
(`tests/unit/qt_app/`: `test_stf.py`, `test_registry.py`) que corren en cualquier
entorno con numpy/scipy, sin necesitar PySide6 ni display.

## 5. Qué queda (alcance explícito para una fase posterior)

- Migrar el flujo de revisión de candidatos (Fase 8: lista filtrable, detalle con
  cadena de evidencia completa, Conservar/Descartar/Marcar) a este mismo shell como
  un proceso/vista más -- es el paso que de verdad completa "un solo framework de
  interfaz" para el producto comercial final.
- Vista de conjunto de fotogramas (múltiples imágenes a la vez) para bias/dark/flat
  maestros y aritmética de dos imágenes.
- Interacción de selección de posiciones sobre la imagen (clic para centroide) para
  fotometría de PSF y trazado espectral.
- Persistencia de "iconos de proceso" guardados con parámetros configurados,
  reutilizables entre sesiones (hoy la configuración vive solo mientras el panel de
  propiedades está abierto).
- Conectar `services/hardware_service.py` (diagnóstico de equipo, Fase 8) al taller
  nuevo -- hoy solo vive en la GUI en Tkinter conservada como referencia.
