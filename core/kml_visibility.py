"""Normal KMZ only: preserve geometry and assets, switch all layers off."""
from xml.etree import ElementTree as ET

KML_NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', KML_NS)
ET.register_namespace('gx', 'http://www.google.com/kml/ext/2.2')
FEATURES = {'Document','Folder','Placemark','GroundOverlay','ScreenOverlay','PhotoOverlay','NetworkLink'}
GEOMETRIES = {'Point','Polygon','LineString','MultiGeometry','LinearRing','Track','MultiTrack'}


def hidden_kml(content: bytes) -> bytes:
    root = ET.fromstring(content)
    first_document = True
    for element in root.iter():
        name = element.tag.rsplit('}', 1)[-1]
        if name not in FEATURES | GEOMETRIES:
            continue
        visibility = element.find(f'{{{KML_NS}}}visibility')
        if visibility is None:
            visibility = ET.SubElement(element, f'{{{KML_NS}}}visibility')
        visibility.text = '0'
        if name in {'Document','Folder'}:
            opened = element.find(f'{{{KML_NS}}}open')
            if opened is None:
                opened = ET.SubElement(element, f'{{{KML_NS}}}open')
            opened.text = '1' if name == 'Document' and first_document else '0'
            if name == 'Document':
                first_document = False
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)
