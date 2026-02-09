"""Fetch canopy NDVI from Google Earth Engine (Sentinel-2, 10m resolution).

Outputs JSON: {"ndvi": 0.42, "prev_ndvi": 0.38, "date": "2026-02-05"}
Uses service account credentials from GEE_SERVICE_ACCOUNT_KEY env var.
"""
import ee
import json
import os
import sys
from datetime import datetime, timedelta

def main():
    lat = float(os.environ.get('LAT', '37.44783'))
    lon = float(os.environ.get('LON', '-122.13604'))

    # Auth
    key = json.loads(os.environ['GEE_SERVICE_ACCOUNT_KEY'])
    credentials = ee.ServiceAccountCredentials(key['client_email'], key_data=json.dumps(key))
    ee.Initialize(credentials, project=key['project_id'])

    point = ee.Geometry.Point(lon, lat)
    now = datetime.utcnow()

    # Sentinel-2 Surface Reflectance, cloud-filtered, last 60 days
    s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
          .filterBounds(point)
          .filterDate((now - timedelta(days=60)).strftime('%Y-%m-%d'), now.strftime('%Y-%m-%d'))
          .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
          .sort('system:time_start', False))

    images = s2.toList(5)
    size = images.size().getInfo()

    if size == 0:
        print(json.dumps({"ndvi": 0, "prev_ndvi": 0, "date": ""}))
        return

    def get_ndvi(img):
        img = ee.Image(img)
        nir = img.select('B8')
        red = img.select('B4')
        ndvi = nir.subtract(red).divide(nir.add(red))
        val = ndvi.reduceRegion(ee.Reducer.mean(), point.buffer(200), 10).getInfo()
        ts = img.get('system:time_start').getInfo()
        date = datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%d')
        return val.get('B8', 0) or 0, date

    ndvi_val, date = get_ndvi(images.get(0))
    prev_ndvi = 0
    if size >= 2:
        prev_ndvi, _ = get_ndvi(images.get(1))

    result = {
        "ndvi": round(ndvi_val, 4),
        "prev_ndvi": round(prev_ndvi, 4),
        "date": date,
    }
    print(json.dumps(result))

if __name__ == '__main__':
    main()
