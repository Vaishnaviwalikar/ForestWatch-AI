import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://data.dataspace.copernicus.eu/odata/v1/Products"
ACCESS_TOKEN = os.environ.get("COPERNICUS_ACCESS_TOKEN", "")

if not ACCESS_TOKEN:
    print("❌ COPERNICUS_ACCESS_TOKEN environment variable not set.")
    exit(1)

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

params = {
    "$filter": "contains(Name, 'S2A_MSIL2A')"
}

response = requests.get(API_URL, headers=headers, params=params)
if response.status_code == 200:
    print("Sentinel-2 Images Retrieved Successfully!")
    data = response.json()
    print(data)
else:
    print("Error Fetching Data:", response.status_code, response.text)
