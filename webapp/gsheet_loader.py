import pickle
import os.path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pandas as pd

# https://developers.google.com/sheets/api/samples/reading
# https://www.googleapis.com/auth/spreadsheets.readonly
# https://towardsdatascience.com/how-to-import-google-sheets-data-into-a-pandas-dataframe-using-googles-api-v4-2020-f50e84ea4530


def gsheet_api_check(SCOPES):
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)    
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'gsheets_secret_creds.json', SCOPES)
                creds = flow.run_local_server(port=0)        
            
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)    
    
    return creds



def pull_sheet_data(SCOPES,SPREADSHEET_ID,RANGE_NAME):
    creds = gsheet_api_check(SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME).execute()
    values = result.get('values', [])
    
    if not values:
        print('No data found.')
    else:
        rows = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                  range=RANGE_NAME).execute()
        data = rows.get('values')
        print("COMPLETE: Data copied")
        return data


SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = '1jsiXkTBoz0iJN6sZUSBcPvZqLbYjPDIYKvr2dUBDBBY'
RANGE_NAME = '10_15_7months_final!A:I'

data = pull_sheet_data(SCOPES,SPREADSHEET_ID,RANGE_NAME)
df = pd.DataFrame(data[1:], columns=data[0])
print(df)