"""Legacy entry point; the normal KMZ UI is maintained in its dedicated page."""
def run_kmz_ui():
    import streamlit as st
    st.page_link("pages/app_mapper_azimuth.py",label="Abrir generador KMZ Azimut")

def build_kmz(df):
    import io
    import zipfile
    from html import escape
    import pandas as pd
    import simplekml
    from core.kml_visibility import hidden_kml
    kml = simplekml.Kml()
    for _, row in df.iterrows():
        lat, lon = pd.to_numeric(row.get("Latitud"),errors="coerce"), pd.to_numeric(row.get("Longitud"),errors="coerce")
        if pd.isna(lat) or pd.isna(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        point = kml.newpoint(name=str(row.get("Tipo","Evento")), coords=[(float(lon),float(lat))])
        point.description = "<br/>".join(f"<b>{escape(str(c))}:</b> {escape(str(v))}" for c,v in row.items())
    out = io.BytesIO()
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml",hidden_kml(kml.kml().encode("utf-8")))
    return out.getvalue()
