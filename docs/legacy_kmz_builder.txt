# modules/kmz_builder.py
lat = r.get("Latitud")
lon = r.get("Longitud")
if pd.isna(lat) or pd.isna(lon):
continue


p = kml.newpoint(name=f"{r.get('Tipo','')} - {r.get('Número A','')}→{r.get('Número B','')}",
coords=[(float(lon), float(lat))])
descr = []
for col in ["Teléfono", "Tipo", "Número A", "Número B", "Fecha", "Hora", "Duración (seg)", "IMEI", "PLUS_CODE", "FechaHora"]:
if col in df.columns:
descr.append(f"<b>{col}:</b> {r.get(col)}")
p.description = "<br/>".join(descr)
stl = _style_for(str(r.get("Tipo", "")))
p.style.iconstyle.color = stl["color"]
p.style.iconstyle.scale = 1.1


# Exportar a KMZ (zip del .kml)
kml_buf = io.BytesIO()
kml.save(kml_buf)
kml_buf.seek(0)


kmz_buf = io.BytesIO()
with zipfile.ZipFile(kmz_buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
zf.writestr("doc.kml", kml_buf.getvalue())
kmz_buf.seek(0)


return kmz_buf.getvalue()




def run_kmz_ui():
st.subheader("Generador de KMZ")
st.caption("Usa el DataFrame limpio de la pestaña anterior o sube otro Excel compatible.")


df = None
use_session = st.checkbox("Usar datos limpios de la pestaña anterior", value=True)


if use_session and "gomapper_df" in st.session_state:
df = st.session_state["gomapper_df"]
else:
up = st.file_uploader("Sube un .xlsx para KMZ", type=["xlsx"], key="kmz_upload")
if up:
try:
df = pd.read_excel(up)
except Exception as e:
st.error("No se pudo leer el Excel.")
st.exception(e)
return


if df is None:
st.info("No hay datos disponibles. Sube un archivo o usa los de la pestaña de Limpieza.")
return


required = {"Latitud", "Longitud"}
if not required.issubset(set(df.columns)):
st.error("Faltan columnas de Latitud/Longitud en los datos.")
return


st.write("Vista previa de los datos que se usarán para KMZ:")
st.dataframe(df.head(50))


if st.button("Generar KMZ"):
try:
kmz_bytes = build_kmz(df)
st.success("KMZ generado.")
st.download_button(
label="⬇️ Descargar KMZ",
data=kmz_bytes,
file_name="GoMapper_Salida.kmz",
mime="application/vnd.google-earth.kmz",
)
except Exception as e:
st.error("No se pudo generar el KMZ.")
st.exception(e)
