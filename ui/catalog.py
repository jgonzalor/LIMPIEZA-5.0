"""Single source of navigation and launcher module descriptions."""
VERSION = '4.1.1'
MODULES = [
 ('Preparación','app armonizador a telcel.py','🔁','Armonizador','Convierte formatos de distintas compañías al esquema común de trabajo.'),
 ('Preparación','app_limpieza_excel.py','🧹','Limpieza','Normaliza el CDR, unifica DATOS repetidos y genera estadísticas. Incluye modo offline.'),
 ('Análisis','app_consulta_visual.py','📊','Consulta visual','Filtra eventos y consulta tablas y resúmenes del archivo procesado.'),
 ('Análisis','app_linea_tiempo.py','📅','Línea de tiempo','Revisa la secuencia de eventos por día y exporta la cronología.'),
 ('Análisis','app_link_analysis.py','🔗','Análisis de vínculos','Explora comunicaciones entre números y sus métricas de relación.'),
 ('Análisis','app_multi_cdr_links.py','🧬','Multi CDR Links','Cruza archivos de varias líneas para revisar contactos compartidos.'),
 ('Análisis','app_grafo_inteligente.py','🕸️','Grafo Inteligente','Diagrama circular, búsqueda de entidades, contactos comunes y edición validada.'),
 ('Análisis','app_oraculo_cdr.py','🧠','ORÁCULO CDR','Consulta el CDR y revisa las filas que sustentan cada resultado.'),
 ('Geográfico','app_mapa_inteligente.py','🗺️','Mapa Inteligente','Explora antenas por frecuencia, tipo de evento y periodo, con tabla de soporte.'),
 ('Geográfico','app_mapper_azimuth.py','🛰️','KMZ Azimut','Genera sectores y antenas para Google Earth, con las capas apagadas al abrir.'),
 ('Geográfico','app_mapper_presencia_aprox.py','📍','Presencia aproximada','Módulo recuperado del original para representar coberturas aproximadas.'),
 ('Geográfico','app_sentinel_mapper_kmz_pro.py','🌎','KMZ Pro','Coberturas y productos avanzados del módulo Pro existente.'),
 ('Reportes','app_informe_cdr.py','📑','Informe CDR','Construye el informe a partir del CDR procesado y sus estadísticas.'),
 ('Sistema','app_maestro_ubicaciones.py','🗃️','Maestro de ubicaciones','Consulta y administra el catálogo local de antenas y direcciones.'),
]
