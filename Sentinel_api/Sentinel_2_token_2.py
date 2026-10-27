import os
import requests
from dotenv import load_dotenv

load_dotenv()

access_token = os.environ.get("COPERNICUS_ACCESS_TOKEN", "")

if not access_token:
    print("❌ COPERNICUS_ACCESS_TOKEN not set in environment or .env file.")
    exit(1)

url = "https://services.sentinel-hub.com/api/v1/process"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}
payload = {
    "input": {
        "bounds": {
            "bbox": [74.25, 15.45, 74.45, 15.64],
            "crs": "EPSG:4326"
        },
        "data": [
            {
                "type": "S2L2A",
                "dataFilter": {"timeRange": {"from": "2024-01-01", "to": "2024-02-01"}}
            }
        ]
    },
    "output": {
        "width": 512,
        "height": 512,
        "responses": [{"identifier": "default", "format": {"type": "image/png"}}]
    }
}

response = requests.post(url, json=payload, headers=headers)
if response.status_code == 200:
    with open("sentinel_image.png", "wb") as file:
        file.write(response.content)
    print("✅ Image downloaded successfully: sentinel_image.png")
else:
    print(f"❌ Error: {response.text}")
