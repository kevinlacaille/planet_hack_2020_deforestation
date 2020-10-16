import flask
from flask import request, jsonify, redirect
import pandas as pd

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

# load database from csv
brasil_data = pd.read_csv('10_15_7months_final.csv', header=0)
brasil_data.columns.values[0] = 'id'

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
    else:
        return "Error: No id field provided. Please specify an id."

    try:
        base_url = brasil_data[brasil_data['id']==id].iloc[0]['base_url']
    except:
        return "Error: Non existing id."
        
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
