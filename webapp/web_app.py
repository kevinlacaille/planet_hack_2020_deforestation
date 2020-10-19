#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from logging.handlers import TimedRotatingFileHandler

import flask
from flask import request, redirect

import calendar
from collections import namedtuple
import datetime
import os
import json
import requests
from requests.auth import HTTPBasicAuth
import time
import sys

from dotenv import load_dotenv
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

# create Flask app
app = flask.Flask(__name__)

# load Flask app config from file
app.config.from_pyfile('web_app_config.cfg')
running_env = app.config['RUNNING_ENV']
debug_mode = app.config['DEBUG_MODE']
logging_file_name = app.config['LOGGING_FILE_NAME']
logging_file_size = app.config['LOGGING_FILE_SIZE']
logging_file_count = app.config['LOGGING_FILE_COUNT']
logging_file_level = app.config['LOGGING_FILE_LEVEL']
database_file_base_name = app.config['DATABASE_FILE_BASENAME']
explorer_base_url=app.config['EXPLORER_BASE_URL']
zoom_level=app.config['DEFAULT_ZOOM']
LAT = app.config['LAT_COLUMN']
LONG = app.config['LONG_COLUMN']
WEEKS_LEFT = app.config['WEEKS_LEFT_OF_DATE']
WEEKS_RIGHT = app.config['WEEKS_RIGHT_OF_DATE']

# load required env vars, hopefully set in .env file
load_dotenv()
PLANET_API_KEY = os.getenv('PL_API_KEY')
if PLANET_API_KEY is None:
    app.logger.error('Env variable PL_API_KEY is not defined. Please set it with your Planet API key in ./.env')
    sys.exit(1)
SECRET_KEY = os.getenv('FLASK_SECRET_KEY')
if SECRET_KEY is None:
    app.logger.error('Env variable FLASK_SECRET_KEY is not defined. Please set it with a custom secret value in ./.env')
    sys.exit(1)
app.config['SECRET_KEY'] = SECRET_KEY

# configure logging according to settings defined in config file
formatter = logging.Formatter(
    "[%(asctime)s] {%(filename)s:%(funcName)s:%(lineno)d} %(levelname)s - %(message)s")
handler = TimedRotatingFileHandler(logging_file_name, when='midnight', backupCount=logging_file_count)
app.logger.setLevel(logging_file_level)
handler.setFormatter(formatter)
app.logger.addHandler(handler)

# Global variables
seconds_per_week = 604800                                       # used by create_times
deg_to_meters_lat_minus_seven = 110590                          # used by create_buffer
five_km_in_deg = 5000/float(deg_to_meters_lat_minus_seven)      # used by create_buffer

# utility functions

def create_times(date, before_weeks=WEEKS_LEFT, after_weeks=WEEKS_RIGHT):
    '''
    Takes in a date as a string, and returns a tuple of (two_weeks_before, 4 weeks after) in Unix time.
    This is used for the end of the url after result::,
    and needs to be one day after before_date and one day before after_date.
    '''
    ## UNIX Conversion ##
    # This standardizes time to UTC
    view_date = calendar.timegm(date.timetuple()) * 1000

    #view_date = time.mktime(date.timetuple()) * 1000
    before_date = view_date - (seconds_per_week * before_weeks * 1000)
    after_date = view_date + (seconds_per_week * after_weeks * 1000)

    ## ISO FORMAT ##
    iso_view_date = datetime.datetime.utcfromtimestamp(after_date/1000).isoformat()+'Z'
    iso_before_date = datetime.datetime.utcfromtimestamp(before_date/1000).isoformat()+'Z'

    return (int(before_date + 86400000), int(after_date - 86400000), iso_before_date, iso_view_date)

def get_time_from_id(image_id):
    '''
    This takes in a full image_id (like the kind in the PSScene4Bands)
    and outputs a Unix timestamp in milliseconds.
    '''
    date = datetime.datetime.strptime(image_id[:8], '%Y%m%d')
    time_in_ms = calendar.timegm(date.timetuple()) * 1000
    return time_in_ms

def create_buffer(row):
    '''
    Takes in a geodataframe row, and returns the row with a new geometry (5km circle around LAT,LONG).
    '''
    dist = five_km_in_deg
    point = row["geometry"]
    row["geometry"] = point.buffer(dist)
    return row

def get_coord_list(geo_row):
    '''
    This takes in a geometry row and uses the .wkt method to create a geojson list of coordinates
    This is a helper function for the get_image_ids function
    '''
    coords = []
    final_coords = []

    for pair in geo_row.wkt[10:].split(','):
        coords.append(pair.strip(' )').split(' '))
    for sublist in coords:
        final_coords.append([float(num) for num in sublist])
    return final_coords

def get_image_ids(coord_list, earlier_time, later_time):

    json_geometry = {'type': 'Polygon', 'coordinates': [coord_list]}

    geometry_filter = {
      "type": "GeometryFilter",
      "field_name": "geometry",
      "config": json_geometry
    }

    # get images acquired within a date range
    date_range_filter = {
      "type": "DateRangeFilter",
      "field_name": "acquired",
      "config": {
        "gte": earlier_time,
        "lte": later_time
      }
    }
    # datetime.datetime.fromisoformat('2020-07-13T00:00:00.000Z'.replace('Z', '+00:00'))
    # unix_ts = calendar.timegm(datetime(2020, 7, 13, 0, 0, tzinfo=timezone.utc).timetuple())
    # final result:: time needs to be these times plus and minus a day


    # only get images which have <50% cloud coverage
    cloud_cover_filter = {
      "type": "RangeFilter",
      "field_name": "cloud_cover",
      "config": {
        "lte": 0.75
      }
    }

    # combine our geo, date, cloud filters
    combined_filter = {
      "type": "AndFilter",
      "config": [geometry_filter, date_range_filter, cloud_cover_filter]      # Rmove
    }

    item_type = "PSScene4Band"

    # API request object
    search_request = {
      "item_types": [item_type],
      "filter": combined_filter
    }

    # fire off the POST request
    search_result = \
      requests.post(
        'https://api.planet.com/data/v1/quick-search',
        auth=HTTPBasicAuth(PLANET_API_KEY, ''),
        json=search_request)

    image_ids = [feature['id'] for feature in search_result.json()['features']]

    app.logger.info(search_result.status_code)

    return image_ids

def get_bands_string(image_ids):
    strings = []
    for s in image_ids:
        strings.append(f'PSScene4Band%3{s},')
    scenes = "".join(strings)
    scenes = scenes[:-1]
    return scenes

def compute_url(row):
    lng_s = "{}".format(row[LONG])
    lat_s = "{}".format(row[LAT])
    scene_date_left = row['UNIX_TIMES'][0]
    scene_date_right = row['UNIX_TIMES'][1]
    date_left = row['UNIX_TIMES'][2]
    date_right = row['UNIX_TIMES'][3]
    image_ids = get_image_ids(get_coord_list(row['geometry']), date_left, date_right)
    id_date_left = get_time_from_id(image_ids[-1])
    id_date_right = get_time_from_id(image_ids[0])
    band_strings = get_bands_string(image_ids)
    base_url = "{}/{},{}/zoom/{}/dates/{}..{}/geometry/{}/items/{}/comparing/result::PSScene4Band:{},result::PSScene4Band:{}".format(
                                explorer_base_url,lat_s,lng_s,zoom_level,date_left,date_right,row['wkt'],band_strings,id_date_left,id_date_right)
    return base_url

def load_database(input_file=database_file_base_name, force_csv=False):
    '''
    Takes in base filename, and returns a geodataframe after either
    - loading a cached pickle version
    - or building a new one from a csv file.
    '''
    if force_csv:
        gdf = load_csv(database_file_base_name)
    else:
        try:
            gdf = pd.read_pickle('{}.pkl'.format(os.path.join(database_file_base_name)))
            app.logger.info('Found existing pickle, using it instead of CSV')
        except Exception as e:
            gdf = load_csv(database_file_base_name)
    return gdf

def load_csv(input_file=database_file_base_name):
    '''
    Takes in base filename, and returns a geodataframe after building a new one from a csv file.
    Used by load_database() when pickle file is not found or rebuilt
    '''
    app.logger.info('1 - Loading CSV')
    df = pd.read_csv('{}.csv'.format(os.path.join(database_file_base_name)), header=0)
    df.columns.values[0] = 'id'

    app.logger.info('2 - Building dates columns')
    # Dates columns
    df['VIEW_DATE'] = df['VIEW_DATE'].apply(lambda row: datetime.datetime.strptime(row, '%Y-%m-%d'))
    # inserting the UNIX_TIMES (2WeeksPrior, ViewDate) into the dataframe after the VIEW_DATE column
    df.insert(4, 'UNIX_TIMES', df.apply(lambda row: create_times(row['VIEW_DATE']), axis=1))

    app.logger.info('3a - Building Wkt column - Point geom')
    geometry = [Point(xy) for xy in zip(df[LAT], df[LONG])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry)
    gdf.crs = 'epsg:4326'

    app.logger.info('3b - Building Wkt column - Buffered geom')
    gdf = gdf.apply(create_buffer,axis=1)
    gdf.crs = 'epsg:4326'

    app.logger.info('3c - Building Wkt column - geom to wkt conversion')
    gdf['wkt'] = gdf.apply(lambda row: row.geometry.simplify(0.0005).wkt.replace(' ',''), axis=1)

    app.logger.info('4 - Saving prebuilt database to pickle')
    gdf.to_pickle('{}.pkl'.format(os.path.join(database_file_base_name)))

    app.logger.info('5 - Finished preparing database, app is ready with {} rows'.format(len(gdf)))
    return gdf

# Flask request handling functions

@app.route('/', methods=['GET'])
def home():
    return '''<h1>Planet Hack 2020</h1>
    <p>URL resolver for Google Sheet data.</p>'''

@app.route('/rebuild', methods=['GET'])
def db_rebuild():
    global brasil_data_buffer_gdf
    brasil_data_buffer_gdf = load_database(force_csv=True)
    return '''<h1>Planet Hack 2020</h1>
    <p>Pickled database rebuilt from CSV</p>'''

@app.route('/api/v1/notice', methods=['GET'])
def api_id():
    # Check if an ID was provided as part of the URL.
    # If ID is provided and exists, redirect to Planet Explorer
    # If no ID is provided, display an error in the browser.
    if 'id' in request.args:
        id = int(request.args['id'])
        app.logger.info('Incoming request with id {}'.format(id))
    else:
        app.logger.warning('Incoming request with no id param')
        return "Error: No id field provided. Please specify an id."

    try:
        row = brasil_data_buffer_gdf[brasil_data_buffer_gdf['id']==id].iloc[0]
        base_url = compute_url(row)
    except Exception as e:
        app.logger.warning(e)
        return "Error: Non existing id or unexpected error."

    # page_content = '<a href="{}">Go to Planet Explorer site</a>'.format(base_url)
    page_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>HTML Meta Tag</title>
            <meta http-equiv = "refresh" content = "1; url = {}" />
        </head>
        <body>
            <p>Redirecting to Planet Explorer site</p>
        </body>
        </html>
    """.format(base_url)
    return (page_content)

##################
#                #
#      Main      #
#                #
##################

brasil_data_buffer_gdf = load_database()

if __name__ == '__main__':

    # get local IP to be accessible from LAN (e.g. for mobile device testing)
    if app.config['LAN_MODE']:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            own_ip = s.getsockname()[0]
            s.close()
            # debug mode is automatically disabled in production environment since not run using __main__
            #own_ip = '127.0.0.1'
            app.run(host=own_ip, debug=debug_mode, port=5001)
        except:
            app.run(debug=debug_mode, port=5001)
    else:
        app.run(debug=debug_mode, port=5001)
