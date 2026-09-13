"""Aggregate observed antenna coordinates without inferring device position."""
import pandas as pd


def aggregate_antennas(frame, latitude, longitude):
    data = frame.copy()
    data['latitude'] = pd.to_numeric(data[latitude],errors='coerce')
    data['longitude'] = pd.to_numeric(data[longitude],errors='coerce')
    valid = data['latitude'].between(-90,90) & data['longitude'].between(-180,180)
    valid &= ~(data['latitude'].eq(0) & data['longitude'].eq(0))
    clean = data[valid].copy()
    # Exact coordinates are retained; nearby antennas are not silently merged.
    grouped = clean.groupby(['latitude','longitude']).size().reset_index(name='eventos')
    grouped['radius'] = grouped['eventos'].pow(.5).mul(5).clip(6,45)
    return clean, grouped.sort_values('eventos',ascending=False), int((~valid).sum())


def render_map_html(antennas, height=660):
    """Embedded Leaflet, no Streamlit/Mapbox token. Only background tiles use network."""
    from pathlib import Path
    import json
    assets=Path(__file__).resolve().parents[1]/'assets'/'leaflet'
    css=(assets/'leaflet.css').read_text()
    js=(assets/'leaflet.js').read_text()
    payload=antennas[['latitude','longitude','eventos','radius']].to_json(orient='records')
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>'+css+
        f'\nhtml,body{{margin:0;height:100%;font-family:Arial,sans-serif;}}#map{{height:{height}px;background:#E8EFF7;}}'+
        '.map-status{position:absolute;z-index:1000;bottom:28px;left:10px;background:white;padding:7px 10px;border-radius:7px;color:#37516D;font-size:12px;}</style></head>'+
        '<body><div id="map"></div><div class="map-status" id="map-status">Antenas registradas · el tamaño indica frecuencia</div><script>'+js+
        '\nconst points='+payload+';'+'''
const map=L.map('map',{preferCanvas:true,scrollWheelZoom:true});
const base=L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',{
 attribution:'&copy; OpenStreetMap contributors &copy; CARTO',maxZoom:19,subdomains:'abcd'}).addTo(map);
base.on('tileerror',()=>{document.getElementById('map-status').textContent='Fondo no disponible · las antenas siguen visibles';});
const group=L.featureGroup().addTo(map);
points.forEach(p=>L.circleMarker([p.latitude,p.longitude],{radius:p.radius,color:'#FFFFFF',weight:1.5,fillColor:'#2563C7',fillOpacity:.75})
.bindTooltip('Antena: '+p.latitude.toFixed(6)+', '+p.longitude.toFixed(6)+'<br>Eventos: '+p.eventos).addTo(group));
if(points.length){map.fitBounds(group.getBounds(),{padding:[35,35],maxZoom:13});}else{map.setView([24.8,-107.4],7);}
</script></body></html>''')
