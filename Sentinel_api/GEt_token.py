import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get("COPERNICUS_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("COPERNICUS_CLIENT_SECRET", "")
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"

def get_access_token():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("❌ Please configure COPERNICUS_CLIENT_ID and COPERNICUS_CLIENT_SECRET in environment or .env file.")
        return None

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

if __name__ == "__main__":
    access_token = get_access_token()
    if access_token:
        print("✅ Access Token retrieved successfully!")
    else:
        print("Failed to retrieve access token.")
