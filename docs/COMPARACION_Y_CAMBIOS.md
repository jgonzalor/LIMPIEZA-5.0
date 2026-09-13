# Comparación e integración — Go Mapper Suite 4.1.1

## Fuentes y alcance

Se compararon los dos ZIP adjuntos: `limpieza-4.0-main.zip` y `Lab-Mapper-main.zip`. La comparación se basó en sus archivos reales, no en la descripción de trabajos de conversaciones anteriores. Lab se utilizó como base de integración; se recuperó el módulo presente solo en el original. Los ZIP recibidos no se modificaron.

`COMPARACION_ARCHIVOS.csv` identifica por ruta qué era igual, qué había cambiado y qué se añadió o modificó en esta entrega. `FUENTES_SHA256.txt` identifica los ZIP comparados.

## Hallazgos relevantes

| Área | Lo encontrado en los ZIP | Resultado en 4.1.1 |
|---|---|---|
| Interfaz | Lab agrega componentes visuales, pero las páginas mantienen distintas navegaciones | Catálogo único de 14 herramientas, portada con búsqueda y filtros, menú compartido y uso del ancho disponible |
| Presencia aproximada | Existe en el original y falta en Lab | Recuperado; accesible desde el menú y la portada |
| Limpieza offline | Lab conserva GEOCODE_ENABLED=True; no existe una opción operativa offline | Offline inicial, sin consultas externas de ubicación; online opcional con límite configurable |
| Geocodificación | Segunda pasada de direcciones podía superar el límite de la pasada principal | Eliminada la segunda pasada de red; fallback a nombre conservado o coordenada |
| Geopy | Tiempo de espera entre errores inferior al intervalo mínimo del RateLimiter | Parámetros compatibles para evitar la aserción del proveedor |
| Caché SQLite | Consulta de todas las coordenadas con un único conjunto de parámetros | Lectura por bloques de 400 coordenadas |
| Fechas | La limpieza sobrescribía Datetime; detección limitada en cronología | Parser compartido; conserva hora sin zona y convierte offsets explícitos a America/Mazatlan |
| Deduplicación | DATOS con NaT podían agruparse como si fueran del mismo minuto | No elimina filas sin fecha o extremos válidos; mantiene llamadas; conserva mayor duración entre DATOS del mismo minuto |
| Descarga de limpieza | Resultado disponible solo durante la ejecución del botón | Resultado persistente en sesión, ligado al archivo y sus opciones; vista previa |
| Línea de tiempo | Guardián no devolvía True; podía detener una sesión válida. Caso vacío producía KeyError | Contrato del guardián corregido, Datetime reconocido y conjunto vacío manejado |
| HTML de cronología | CSS genérico de un documento completo inyectado en la página principal | HTML aislado en un marco con desplazamiento; no altera el resto de la suite |
| ZIP de cronologías | Nombres con comillas no adecuados para Windows; descarga de filtros antiguos | Nombres compatibles con Windows e invalidación al cambiar archivo o tipos |
| APN de cronología | Fallback asignaba internet.telcel aunque no existiera en el archivo | Muestra APN no informado |
| Grafo Inteligente | Editor básico sin validación clara; errores de render ocultados como dependencia ausente | Vista circular/dinámica, foco y saltos, umbral, contactos comunes, edición validada, exports y mensajes específicos |
| Mapa Inteligente | No hay página con este nombre en ninguno de los dos ZIP | Nueva página de antenas con filtros y filas de soporte; Leaflet embebido evita solicitud de token Mapbox de Streamlit |
| KMZ normal | Constructor activa carpetas al generar | Apagado de capas aplicado al KML final, conservando geometrías y archivos internos |
| KMZ Pro | Núcleo avanzado existente | Núcleo de construcción/estilos/análisis preservado; integración visual y configuración de página unificadas |
| Acceso | Grafo básico no aplicaba el guardián | Usa el mismo control de acceso; salir limpia los datos de la sesión |
| Auxiliares | modules/auth.py y modules/kmz_builder.py no compilaban en ambas bases | Adaptadores válidos; fragmentos originales conservados como texto en docs/legacy_* |
| Dependencias | Se anuncia XLS sin xlrd y PyVis estaba repetido | Añadido xlrd; eliminada duplicación de PyVis; conservada versión Streamlit |
| Navegación | LEX se anuncia pero el archivo no existe en ninguno de los ZIP; Multi CDR no figura en el lanzador | Sin acceso ficticio a LEX; Multi CDR accesible |

## Nueva organización visual

Paleta azul, fondo claro y contraste legible; menú lateral compacto; buscador por nombre o función; filtros por etapa; tarjetas con descripciones operativas. La búsqueda admite tildes. KMZ, presencia aproximada y catálogo utilizan la navegación común. El control para reabrir el menú lateral permanece visible.

El Grafo prioriza el diagrama: carga plegable después de importar, indicadores, filtros y pestañas para relaciones/soporte, edición y exportación. Los cambios de edición se validan juntos y se guardan explícitamente. No acepta identificadores duplicados, extremos inexistentes ni pesos fraccionarios, no positivos o infinitos.

El Mapa agrupa por coordenada exacta, sin unir antenas próximas automáticamente. Rechaza coordenadas fuera de rango y 0,0; permite elegir campos y periodo. Cada evento de soporte conserva nombre de archivo y fila Excel de la hoja seleccionada. Las coordenadas se dibujan localmente; si fallan las teselas, se informa y permanecen visibles los puntos.

## Semántica y exportaciones

- Hora sin zona: se respeta como hora local de origen. Hora con offset: se convierte a America/Mazatlan antes de exportar una fecha sin zona compatible con Excel. No se supone que toda hora recibida sea UTC.
- La limpieza conserva las hojas Datos_Limpios, LOG_Limpieza y ESTADISTICAS; Duplicados aparece cuando hay eliminaciones.
- Grafo desde CDR: el analista confirma origen/destino. A/B no se interpretan universalmente como llamada originada/recibida. DATOS/GPRS/INTERNET se excluyen inicialmente del selector de eventos para relaciones entre líneas.
- Titulares y usuarios son campos documentados por el analista, no atribuciones automáticas.
- La evidencia original del CDR es independiente de la edición manual del grafo. No se presenta una relación manual como si proviniera de la operadora.
- Excel/JSON del grafo: completo guardado. HTML: diagrama filtrado visible.
- Mapas: representan antenas y frecuencias. No son triangulación ni posición exacta del usuario.
- El apagado del KMZ se aplica a la versión normal; no se aplica al constructor Pro.

## Validación y límites

Se ejecutaron pruebas automatizadas de fechas, deduplicación y limpieza offline, integridad del grafo, filtros y procedencia de filas, coordenadas inválidas, guardián, salida de sesión, cronología/PDF y construcción del KMZ. Las pruebas de navegación recorren las 14 herramientas desde app.py.

Se abrió además la aplicación en Chromium: login, portada, carga de un grafo JSON sintético con canvas visible, carga del mapa con marcadores visibles, limpieza offline y descarga efectiva de Excel, y carga del Excel limpio en cronología con salida PDF disponible. Las capturas en docs/capturas corresponden al navegador de prueba y a datos sintéticos.

El flujo largo de navegador tuvo un timeout esperando el botón PDF tras cambiar de página; una comprobación independiente de la cronología con el mismo Excel mostró las descargas HTML/PDF disponibles sin excepción. La generación PDF también se comprobó en la prueba automatizada.

No se afirma certificación de producción ni validación con todos los formatos históricos de operadoras. No se verificó geocodificación real contra proveedores, disponibilidad de teselas en la red del usuario, despliegue en su cuenta de Streamlit Cloud, ejecución de los CMD en Windows ni apertura visual del KMZ en Google Earth. El KML y sus archivos internos sí se inspeccionaron mediante pruebas.

El catálogo raíz plus_repo.sqlite y el repositorio de limpieza data/plus_repo conservan sus esquemas originales: no se realizó una migración o fusión de catálogos. Los módulos históricos conservan sus cálculos, salvo las correcciones expresamente descritas. ORÁCULO se comprobó en arranque; no se certifican todas sus consultas ni las afirmaciones legales de informes heredados.

## Montaje

Usar un repositorio nuevo o rama de pruebas, con app.py en la raíz y Python 3.12. Mantener los Secrets ya configurados. Las instrucciones y los lanzadores de Windows están en la raíz. El README explica las exportaciones y el modo offline.
