# Requirements

* Python (tested with 3.7)
* virtualenv + virtualenvwrapper
* flask + geopandas + python-dotenv (listed in `requirements.txt`)
* a CSV file containing at least the following columns (column names can be changed in config file)
    * `UNIQUE_ID`: unique id for the observation, used for lookup with the `?id=` URL param
    * `VIEW_DATE`: initial observation date (YYYY-MM-DD)
    * `LAT`: longitude, WGS84/EPSG:4326
    * `LONG`: longitude, WGS84/EPSG:4326

# Installation

## Setting up the virtual environment and getting the project code

```
# cd to some path where you usually store all your code projects
$ git clone https://github.com/kevinlacaille/planet_hack_2020_deforestation.git
$ cd planet_hack_2020_deforestation/webapp
$ mkvirtualenv -p python3.7 -a . planet_hack_2020_deforestation_flask
$ pip install -r requirements.txt
```

## Configuring your Planet API key and Flask secret key

Create a `.env` file in the `webapp` folder containing the following lines (adjust `PL_API_KEY` value with your own Planet API key and `FLASK_SECRET_KEY` to a custom secret value)

```
export PL_API_KEY=<your_api_key>
export FLASK_SECRET_KEY=<your_own_secret_key>
```

The Planet API key can be remotely changed using the `/setenv?PL_API_KEY=<your_api_key>` route, provided that `SETENV_ENABLED` is set to `True`in the .cfg file

## Defining CSV file name to load

Edit `DATABASE_FILE_BASENAME`, `ID_COLUMN`, `REFERENCE_DATE`, `LAT_COLUMN` and `LONG_COLUMN` in `web_app_config.cfg` to use your own data structure

# Running the application locally

## Starting the application

```
$ workon planet_hack_2020_deforestation
$ python web_app.py
```

On the first run, you should see the CSV file being loaded to build a pickled geodataframe which will be used in subsequent app launches.

You can hit `/rebuild` at any time to force the reconstruction from the CSV file (in case it is updated)

## Testing if the application is working

Open your web browser and go to [http://127.0.0.1:5001/api/v1/notice?id=1](http://127.0.0.1:5001/api/v1/notice?id=1). You should be redirected to a Planet Explore page centered on the `LAT`, `LONG` defined for `id`=1, and a window period defined around the `VIEW_DATE` value. 

# Available routes and parameters

* `/`: home page, basically a project banner
* `/setenv`: if enabled, provides remote access to change Planet API Key
    * example: `GET /setenv?PL_API_KEY=<your_api_key>`
* `/rebuild`: forces reconstruction of the pickled dataframe used a cache from an input CSV. Useful if CSV file has been updated or if global parameters have been modified
    * example: `GET /rebuild`
* `/api/v1/notice`: main route of the application
    * mandatory params:
        - `id`: unique id of a row (int)
    * optional params:
        - `rm`: Radius in Meters around the coordinates to create circle or share shape (int)
        - `sh`: `ci` or `sq`: 'CIrcle' or 'SQuare' SHape centered on point (string)
        - `db`: number of Days Before date in database for beginning of image search period (int)
        - `da`: number of Days After date in database for end of image search period (int)
        - `cc`: max Cloud Cover accepted (int, 0 to 100)
    * full example: `GET /api/v1/notice?id=1&rm=5000&sh=ci&db=14&da=28&cc=25`

# Available configuration parameters

* see `web_app_config.cfg` file content
