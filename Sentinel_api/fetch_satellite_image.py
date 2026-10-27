import requests
from requests.auth import HTTPBasicAuth

# Replace with your actual CLIENT_ID and CLIENT_SECRET
CLIENT_ID = "sh-6d51f7ff-20b4-4851-a0fb-245123a2760c"
CLIENT_SECRET = "u36uLRkBP38iYofhaIqhYAFG66TYmsHs"

# Sentinel Hub Token URL
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"

def get_access_token():
    response = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
    )
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        print("Failed to obtain access token:", response.json())
        return None

# Get access token
access_token = get_access_token()

if access_token:
    print("Access Token:", access_token[:50] + "...")  # Print only part of the token
else:
    print("Failed to retrieve access token")
