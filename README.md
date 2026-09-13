# Go Mapper Suite 4.1.1

Versión integrada a partir de `limpieza-4.0-main.zip` y `Lab-Mapper-main.zip` entregados por el usuario. Conserva los módulos del original, utiliza Lab como base visual y agrega las correcciones documentadas en `docs/COMPARACION_Y_CAMBIOS.md`.

## Montaje en Streamlit Cloud

1. Descomprime el ZIP y sube **el contenido de la carpeta Go-Mapper-Suite-4.1.1** a un repositorio nuevo o a una rama de pruebas. `app.py`, `requirements.txt`, `pages`, `core`, `ui` y `assets` deben quedar en la raíz del repositorio.
2. En Streamlit Cloud selecciona `app.py` y Python **3.12**.
3. Conserva la configuración de Secrets de tu instalación actual. Esta entrega mantiene los esquemas de credenciales existentes del guardián.
4. Arranca y carga primero un archivo de prueba. Usa Limpieza offline para comprobar el flujo sin consultar direcciones.

La versión conserva Streamlit 1.35.0; se ajustó la configuración visual a esa versión. No se cambian los requisitos a versiones mayores sin comprobar compatibilidad.

## Windows local

Instala Python 3.12. Ejecuta `INSTALAR_WINDOWS.cmd` una vez y después `INICIAR_WINDOWS.cmd`.

Alternativa manual desde la carpeta del proyecto:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

La instalación de dependencias requiere internet. El modo offline de Limpieza evita las consultas a servicios de ubicación; no convierte los mapas base web en cartografía offline.

## Uso recomendado

- Armonizador → Limpieza → Consulta / Grafo / Cronología → Mapa / KMZ / Informe.
- Limpieza: offline inicial; online opcional con límite de coordenadas únicas consultadas.
- Grafo: JSON con `nodos` / `aristas`, Excel con hojas `NODOS` / `ARISTAS`, o CDR limpio con mapeo explícito de origen y destino. Los identificadores deben ser texto para conservar ceros iniciales.
- Grafo: el filtro afecta el diagrama; Excel y JSON exportan el grafo completo guardado. HTML exporta la vista visible.
- Mapa: usa coordenadas decimales del CDR limpio. El tamaño del punto indica frecuencia, nunca radio de cobertura.
- KMZ normal: capas apagadas y árbol disponible al abrir. KMZ Pro conserva su lógica de construcción.

Titulares y usuarios son datos documentados por el analista. La aplicación no identifica personas automáticamente. Las antenas y sectores no demuestran una posición exacta del dispositivo.

## Verificación

```powershell
.venv\Scripts\python.exe -m pip install pytest
.venv\Scripts\python.exe -m pytest tests -q
```

Las pruebas usan datos sintéticos; no incluyen CDR reales. Consulta el informe para distinguir pruebas funcionales de servicios externos no comprobados.
