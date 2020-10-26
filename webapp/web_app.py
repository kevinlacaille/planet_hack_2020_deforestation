#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from logging.handlers import TimedRotatingFileHandler

import flask
from flask import request, redirect
from flask_debugtoolbar import DebugToolbarExtension

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
from shapely.geometry import Point, shape
from geopy import distance

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
redirect_delay = app.config['REDIRECT_DELAY']
explorer_base_url=app.config['EXPLORER_BASE_URL']
zoom_level=app.config['DEFAULT_ZOOM']
LAT = app.config['LAT_COLUMN']
LONG = app.config['LONG_COLUMN']
ID = app.config['ID_COLUMN']
REFERENCE_DATE = app.config['REFERENCE_DATE_COLUMN']
intersection_filter = app.config['INTERSECTION_FILTER']
days_before_date = app.config['DAYS_BEFORE_REFERENCE_DATE']
days_after_date = app.config['DAYS_AFTER_REFERENCE_DATE']
radius = app.config['DEFAULT_RADIUS']
simplification_threshold = app.config['SIMPLIFICATION_THRESHOLD']
default_cloud_cover = app.config['MAX_CLOUD_COVER']

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

# debug toolbar will only appear when Debug = True (needs to be after SECRET_KEY and DEBUG are set)
app.debug = debug_mode
toolbar = DebugToolbarExtension(app)

# configure logging according to settings defined in config file
formatter = logging.Formatter(
    "[%(asctime)s] {%(filename)s:%(funcName)s:%(lineno)d} %(levelname)s - %(message)s")
handler = TimedRotatingFileHandler(logging_file_name, when='midnight', backupCount=logging_file_count)
app.logger.setLevel(logging_file_level)
handler.setFormatter(formatter)
app.logger.addHandler(handler)

# Global variables
seconds_per_day = 86400                                                 # used by create_times
millisecs_per_day = seconds_per_day * 1000                              # used by create_times

# utility functions

def create_times(date, days_before=days_before_date, days_after=days_after_date):
    '''
    Takes in a date as a string, and returns a tuple of (x days before, y days after) in Unix time.
    This is used for the end of the url after result::,
    and needs to be one day after before_date and one day before after_date.
    '''
    ## UNIX Conversion ##
    # This standardizes time to UTC
    view_date = calendar.timegm(date.timetuple()) * 1000

    #view_date = time.mktime(date.timetuple()) * 1000
    before_date = view_date - (seconds_per_day * days_before * 1000)
    after_date = view_date + (seconds_per_day * days_after * 1000)

    ## ISO FORMAT ##
    iso_after_date = datetime.datetime.utcfromtimestamp(after_date/1000).isoformat()+'Z'
    iso_before_date = datetime.datetime.utcfromtimestamp(before_date/1000).isoformat()+'Z'

    return (int(before_date + millisecs_per_day), int(after_date - millisecs_per_day), iso_before_date, iso_after_date)

def get_time_from_id(image_id):
    '''
    This takes in a full image_id (like the kind in the PSScene4Bands)
    and outputs a Unix timestamp in milliseconds.
    '''
    date = datetime.datetime.strptime(image_id[:8], '%Y%m%d')
    time_in_ms = calendar.timegm(date.timetuple()) * 1000
    return time_in_ms

def one_degree_lat_as_meters(lat=0.0):
    # take 2 points 0.5° higher/lower than reference, compute distance in meters using best method in GeoPy (currently geodetic)
    point1 = (0.0, lat + 0.5)
    point2 = (0.0, lat - 0.5)
    return distance.distance(point1, point2).m

def create_buffer(row):
    '''
    Takes in a geodataframe row, and returns the row with a new geometry (x km circle around LAT,LONG).
    '''
    deg_to_meters = one_degree_lat_as_meters(lat=row[LAT])                          
    radius_in_deg = radius/float(deg_to_meters)             
    point = row["geometry"]
    row["geometry"] = point.buffer(radius_in_deg)
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

def get_image_ids(coord_list, earlier_time, later_time, max_cloud_cover=default_cloud_cover):

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

    # only get images which have less than a set cloud coverage (defined in configuration file, default 75%) 
    cloud_cover_filter = {
      "type": "RangeFilter",
      "field_name": "cloud_cover",
      "config": {
        "lte": max_cloud_cover/100.
      }
    }

    # only 'finalized' images
    finalized_filter = {  
        "type":"StringInFilter",
        "field_name":"publishing_stage",
        "config":["finalized"]
        }
    
    # combine our geo, date, cloud filters
    combined_filter = {
      "type": "AndFilter",
      "config": [geometry_filter, date_range_filter, cloud_cover_filter, finalized_filter]      # Rmove
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

    # filter by % of interesection with AOI
    aoi = shape(json_geometry)
    ratio = [aoi.intersection(shape(feature['geometry'])).area/aoi.area for feature in search_result.json()['features']]
    filtered_ids = [i for (i, v) in zip(image_ids, ratio) if v >= intersection_filter/100]

    app.logger.info(search_result.status_code)

    return sorted(filtered_ids, reverse=True)

def get_bands_string(image_ids):
    strings = []
    for s in image_ids:
        strings.append(f'PSScene4Band%3{s},')
    scenes = "".join(strings)
    scenes = scenes[:-1]
    return scenes

def compute_url(row, max_cloud_cover=default_cloud_cover):
    lng_s = "{}".format(row[LONG])
    lat_s = "{}".format(row[LAT])
    scene_date_left = row['UNIX_TIMES'][0]
    scene_date_right = row['UNIX_TIMES'][1]
    date_left = row['UNIX_TIMES'][2]
    date_right = row['UNIX_TIMES'][3]
    image_ids = get_image_ids(get_coord_list(row['geometry']), date_left, date_right, max_cloud_cover=max_cloud_cover)
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

    app.logger.info('2 - Building dates columns')
    # Dates columns
    df[REFERENCE_DATE] = df[REFERENCE_DATE].apply(lambda row: datetime.datetime.strptime(row, '%Y-%m-%d'))
    # inserting the UNIX_TIMES (X days prior, y days after) into the dataframe after the REFERENCE_DATE column
    df.insert(4, 'UNIX_TIMES', df.apply(lambda row: create_times(row[REFERENCE_DATE]), axis=1))

    app.logger.info('3a - Building Wkt column - Point geom')
    geometry = [Point(xy) for xy in zip(df[LONG], df[LAT])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry)
    gdf.crs = 'epsg:4326'

    app.logger.info('3b - Building Wkt column - Buffered geom')
    gdf = gdf.apply(create_buffer,axis=1)
    gdf.crs = 'epsg:4326'

    app.logger.info('3c - Building Wkt column - geom to wkt conversion')
    gdf['wkt'] = gdf.apply(lambda row: row.geometry.simplify(simplification_threshold).wkt.replace(' ',''), axis=1)

    app.logger.info('4 - Saving prebuilt database to pickle')
    gdf.to_pickle('{}.pkl'.format(os.path.join(database_file_base_name)))

    app.logger.info('5 - Finished preparing database, app is ready with {} rows'.format(len(gdf)))
    return gdf

# Flask request handling functions

html_base = '''
    <html><body>
    {}
    </body></html>
'''

@app.route('/', methods=['GET'])
def home():
    return html_base.format('''
    <h1>Planet Hack 2020</h1>
    <p>URL resolver for Google Sheet data.</p>
    ''')

@app.route('/rebuild', methods=['GET'])
def db_rebuild():
    global db_gdf
    db_gdf = load_database(force_csv=True)
    return html_base.format('''
    <h1>Planet Hack 2020</h1>
    <p>Pickled database rebuilt from CSV</p>
    ''')

@app.route('/api/v1/notice', methods=['GET'])
def api_id():
    '''
    route handling redirection requests
    mandatory params:
    - id: unique id of a row (int)
    optional params:
    - rm: Radius in Meters around the coordinates to create circle (int)
    - db: number of Days Before date in database for beginning of image search period (int)
    - da: number of Days After date in database for end of image search period (int)
    - cc: max cloud cover accepted (int, 0 to 100)
    '''

    # Check if an ID was provided as part of the URL.
    # If ID is provided and exists, redirect to Planet Explorer
    # If no ID is provided, display an error in the browser.
    if 'id' in request.args:
        id = int(request.args['id'])
        app.logger.info('Incoming request with id {}'.format(id))
    else:
        app.logger.warning('Incoming request with no id param')
        return html_base.format("<p>Error: No id field provided. Please specify an id.<p>")

    # handle radius optional parameter
    if 'rm' in request.args:
        custom_radius = int(request.args['rm'])
    else:
        custom_radius = radius

    # handle "days before" optional parameter
    if 'db' in request.args:
        custom_days_before_date = int(request.args['db'])
    else:
        custom_days_before_date = days_before_date

    # handle "days after" optional parameter
    if 'da' in request.args:
        custom_days_after_date = int(request.args['da'])
    else:
        custom_days_after_date = days_after_date

    # handle "days before" optional parameter
    if 'cc' in request.args:
        custom_cloud_cover = int(request.args['cc'])
    else:
        custom_cloud_cover = default_cloud_cover

    # search for row with provided id
    try:
        # take first row matching id
        row = db_gdf[db_gdf[ID]==id].iloc[0]
        # temporarily update row geometry with new radius if provided
        if (custom_radius != radius):
            custom_radius_in_deg = custom_radius/float(one_degree_lat_as_meters(lat=row[LAT])) 
            row['geometry'] = Point(row[LONG], row[LAT]).buffer(custom_radius_in_deg)
            row['wkt'] = row['geometry'].simplify(simplification_threshold).wkt.replace(' ','')
        if (custom_days_before_date != days_before_date) or (custom_days_after_date != days_after_date):
            row['UNIX_TIMES'] = create_times(row[REFERENCE_DATE], custom_days_before_date, custom_days_after_date)
        # compute redirect URL from default and updated parameters
        base_url = compute_url(row, max_cloud_cover=custom_cloud_cover)
    except Exception as e:
        app.logger.warning(e)
        return html_base.format("<p>Error: Non existing id or unexpected error.</p>")
 
    # page_content = '<a href="{}">Go to Planet Explorer site</a>'.format(base_url)
    page_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>HTML Meta Tag</title>
            <meta http-equiv = "refresh" content = "{}; url = {}" />
        </head>
        <body>
            <p>Redirecting to Planet Explorer site with the following settings:</p>
            <ul>
            <li>Map centered on (Lat, Lng) = ({}, {})</li>
            <li>Radius = {} m</li>
            <li>Max cloud cover = {}%</li>
            <li>Min footprint intersection with AOI = {}%</li>
            <li>Reference date: {}</li>
            <li>'Before' date: {} ({} days before reference date)</li>
            <li>'After' date: {} ({} days after reference date)</li>
            </ul>
        </body>
        </html>
    """.format(redirect_delay, base_url, row[LAT], row[LONG], 
            custom_radius, custom_cloud_cover, intersection_filter, row[REFERENCE_DATE], 
            row['UNIX_TIMES'][2], custom_days_before_date, 
            row['UNIX_TIMES'][3], custom_days_after_date)
    return (page_content)

##################
#                #
#      Main      #
#                #
##################

db_gdf = load_database()

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
