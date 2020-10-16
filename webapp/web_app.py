#!/usr/bin/python
# -*- coding: utf-8 -*-

# proper logging setup
import logging
#from logging.handlers import RotatingFileHandler
from logging.handlers import TimedRotatingFileHandler

import flask
from flask import request, jsonify, redirect

import calendar
from collections import namedtuple
import datetime
import os
import json
import requests
from requests.auth import HTTPBasicAuth
import time

from dotenv import load_dotenv
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

load_dotenv()

app = flask.Flask(__name__)
app.config.from_pyfile('web_app_config.cfg')

# load config
app.config["DEBUG"] = True
running_env = app.config['RUNNING_ENV']
debug_mode = app.config['DEBUG_MODE']
logging_file_name = app.config['LOGGING_FILE_NAME']
logging_file_size = app.config['LOGGING_FILE_SIZE']
logging_file_count = app.config['LOGGING_FILE_COUNT']
logging_file_level = app.config['LOGGING_FILE_LEVEL']
csv_file = app.config['DATABASE']

# configure logging according to user defined settings
formatter = logging.Formatter(
    "[%(asctime)s] {%(filename)s:%(funcName)s:%(lineno)d} %(levelname)s - %(message)s")
# handler = RotatingFileHandler(logging_file_name, maxBytes=logging_file_size, backupCount=logging_file_count)
handler = TimedRotatingFileHandler(logging_file_name, when='midnight', backupCount=logging_file_count)
app.logger.setLevel(logging_file_level)
handler.setFormatter(formatter)
app.logger.addHandler(handler)

# utility functions

seconds_per_week = 604800
def create_times(date, before_weeks=2, after_weeks=4):
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

deg_to_meters_lat_minus_seven = 110590
five_km_in_deg = 5000/110590.
def create_buffer(row):
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

#### NOTE: Your Planet API key needs to be in a .env file inside this directory for this cell to work ####

def get_image_ids(coord_list, earlier_time, later_time):

    console.logger.info('get_image_ids')

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

    # API Key stored as an env variable
    PLANET_API_KEY = os.getenv('PL_API_KEY')


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
    
    return image_ids 

def get_bands_string(image_ids):

    console.logger.info('get_bands_string')


    strings = []
    for s in image_ids:
        strings.append(f'PSScene4Band%3{s},')
    scenes = "".join(strings)
    scenes = scenes[:-1]
    return scenes

explore_base_url = 'https://www.planet.com/explorer/#/mode/compare/interval/1%20day/center'
zoom_base = 13.5

def compute_url(row):
    app.logger.info('compute_url')
    lng_s = "{}".format(row['LONG'])
    lat_s = "{}".format(row['LAT'])
    app.logger.info(lng_s)
    scene_date_left = row['UNIX_TIMES'][0]
    scene_date_right = row['UNIX_TIMES'][1]
    app.logger.info(scene_date_left)
    date_left = row['UNIX_TIMES'][2]
    date_right = row['UNIX_TIMES'][3]
    app.logger.info(date_left)
    band_strings = get_bands_string(get_image_ids(get_coord_list(row['geometry']), date_left, date_right))
    app.logger.info(band_strings)
    base_url = "{}/{},{}/zoom/{}/dates/{}..{}/geometry/{row['wkt']}/items/{}/comparing/result::PSScene4Band:{},result::PSScene4Band:{}".format(
                                explore_base_url,lat_s,lng_s,zoom_base,date_left,date_right,band_strings,scene_date_left,scene_date_right)
    return base_url    

# load database from csv
def load_database(input_file=csv_file):

    app.logger.info('1 - Loading CSV')

    brasil_data = pd.read_csv(csv_file, header=0)
    brasil_data.columns.values[0] = 'id'

    app.logger.info('2 - Building dates columns')

    # Dates columns
    brasil_data['VIEW_DATE'] = brasil_data['VIEW_DATE'].apply(lambda row: datetime.datetime.strptime(row, '%Y-%m-%d'))
    # inserting the UNIX_TIMES (2WeeksPrior, ViewDate) into the dataframe after the VIEW_DATE column
    brasil_data.insert(4, 'UNIX_TIMES', brasil_data.apply(lambda row: create_times(row['VIEW_DATE']), axis=1))

    app.logger.info('3a - Building Wkt column - Point geom')

    # wkt column
    geometry = [Point(xy) for xy in zip(brasil_data.LAT, brasil_data.LONG)]
    brasil_data_gdf = gpd.GeoDataFrame(brasil_data, geometry=geometry)
    brasil_data_gdf.crs = 'epsg:4326'

    app.logger.info('3b - Building Wkt column - Buffered geom')

    brasil_data_buffer_gdf = brasil_data_gdf.apply(create_buffer,axis=1)
    brasil_data_buffer_gdf.crs = 'epsg:4326'

    app.logger.info('3c - Building Wkt column - geom to wkt conversion')

    brasil_data_buffer_gdf['wkt'] = brasil_data_buffer_gdf.apply(lambda row: row.geometry.simplify(0.0005).wkt.replace(' ',''), axis=1)

    app.logger.info('4 - Done loading database')
    return brasil_data_buffer_gdf

brasil_data_buffer_gdf = load_database()

# Bands
# Wrapping everything up, this will take about 8-10 minutes to run
# brasil_data_buffer_gdf['bands_string'] = brasil_data_buffer_gdf.apply(lambda row:
# get_bands_string(get_image_ids(get_coord_list(row['geometry']), row['UNIX_TIMES'][2], row['UNIX_TIMES'][3])), axis=1)

# Flask request handling functions

@app.route('/', methods=['GET'])
def home():
    return '''<h1>Planet Hack 2020</h1>
<p>URL resolver for Google Sheet data.</p>'''

@app.route('/api/v1/notice', methods=['GET'])
def api_id():
    # Check if an ID was provided as part of the URL.
    # If ID is provided, assign it to a variable.
    # If no ID is provided, display an error in the browser.
    if 'id' in request.args:
        id = int(request.args['id'])
        app.logger.info('Incoming request with id {}'.format(id))
    else:
        app.logger.warning('Incoming request with no id param')
        return "Error: No id field provided. Please specify an id."

    try:
        row = brasil_data_buffer_gdf[brasil_data_buffer_gdf['id']==id]
        app.logger.info(row)
        base_url = compute_url(row)
        app.logger.info(base_url)
    except:
        return "Error: Non existing id or unexpected error."
        
    return redirect(base_url)

##################
#                #
#      Main      #
#                #
##################

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
