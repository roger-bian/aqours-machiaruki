import os

from dotenv import load_dotenv

# must run before importing app.db/app.storage, which read connection
# details from the environment at module-import time
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import upsert_locations
from app.description import extract_img_url, parse_description
from app.images import cache_images
from app.kml import fetch_kml, load_placemarks

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
KML_PATH = os.path.join(DATA_DIR, 'machiaruki.kml')
IMG_DIR = os.path.join(DATA_DIR, 'images')

app = FastAPI(title='machiaruki-pipeline')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


def _build_records(placemarks):
    records = []
    for _, row in placemarks.iterrows():
        description = row['Description']
        fields = parse_description(description)
        img_url = extract_img_url(description)
        records.append({
            'name': row['Name'],
            'lat': row.geometry_object.y,
            'lon': row.geometry_object.x,
            'member': fields['member'],
            'address': fields['address'],
            'hours': fields['hours'],
            'holidays': fields['holidays'],
            '_raw_img_url': img_url,
        })
    return records


@app.post('/pipeline/run')
def run_pipeline():
    fetch_kml(KML_PATH)
    placemarks = load_placemarks(KML_PATH)
    records = _build_records(placemarks)

    img_urls = cache_images([r['_raw_img_url'] for r in records], IMG_DIR)
    for record, img_url in zip(records, img_urls):
        record['img_url'] = img_url
        del record['_raw_img_url']

    inserted, updated = upsert_locations(records)
    return {'processed': len(records), 'inserted': inserted, 'updated': updated}


@app.get('/health')
def health():
    return {'status': 'ok'}
