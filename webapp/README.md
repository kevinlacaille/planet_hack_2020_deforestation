# Requirements

* Python (tested with 3.7)
* virtualenv + virtualenvwrapper
* flask + geopandas + python-dotenv (listed in `requirements.txt`)
* a CSV file containing at least the following columns
    * `id`: unique id for the observation, used for lookup with the `?id=` URL param
    * `VIEW_DATE`: initial observation date (YYYY-MM-DD)
    * `LAT`: longitude, WGS84/EPSG:4326
    * `LONG`: longitude, WGS84/EPSG:4326

# Installation

## Setting up the virtual environment and getting the project code

```
$ mkvirtualenv -p python3.7 planet_hack_2020_deforestation_flask
$ git clone https://github.com/kevinlacaille/planet_hack_2020_deforestation.git
$ cd planet_hack_2020_deforestation/webapp
$ pip install -r requirements.txt
```

## Configuring your Planet API key and Flask secret key

Create a `.env` file in the `webapp` folder containing the following lines (adjust `PL_API_KEY` value with your own Planet API key and `FLASK_SECRET_KEY` to a custom secret value)

```
export PL_API_KEY=<your_api_key>
export FLASK_SECRET_KEY=<your_own_secret_key>
```

## Defining CSV file name to load

Edit `DATABASE_CSV` and `DATABASE_PKL` in `web_app_config.cfg` if you want to use your own data

# Running the application locally

## Starting the application

```
$ workon planet_hack_2020_deforestation
$ # cd to where you cloned the repo if needed
$ # cd to webapp subfolder if needed
$ python web_app.py
```

## Testing if the application is working

Open your web browser and go to [http://127.0.0.1:5001/api/v1/notice?id=202](http://127.0.0.1:5001/api/v1/notice?id=202). You should be redirected to a Planet Explore page centered on the `LAT`, `LONG` defined for `id`=202, and a window period defined around the `VIEW_DATE` value
