import os

# GDAL/OGR driver choice matters: this forces GDAL's built-in KML driver
# instead of LIBKML (which system libgdal-dev installs and GDAL otherwise
# prefers). geotable hardcodes a drop-list that deletes the lowercase
# `description` field LIBKML produces; the built-in driver instead exposes
# it capitalized (`Description`), which survives and is what
# parse_description()/extract_img_url() expect. Must be set before
# geotable/osgeo are imported.
os.environ['OGR_SKIP'] = 'LIBKML'

import geotable
import requests

KML_URL = 'https://www.google.com/maps/d/u/0/kml?forcekml=1&mid=1hQhJDhsE87Iu9BJOln-EnveGbow&lid=Cs8qfjzbvoQ'


def fetch_kml(path, url=KML_URL):
    # re-downloads fresh every call - this is triggered explicitly to
    # refresh data, not cached across runs
    os.makedirs(os.path.dirname(path), exist_ok=True)
    response = requests.get(url)
    response.raise_for_status()
    with open(path, 'wb') as f:
        f.write(response.content)
    return path


def load_placemarks(path):
    return geotable.load(path)
