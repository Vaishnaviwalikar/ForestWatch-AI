import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
ACCESS_TOKEN = os.environ.get("COPERNICUS_ACCESS_TOKEN", "")

if not ACCESS_TOKEN:
    print("❌ COPERNICUS_ACCESS_TOKEN not set in environment or .env file.")
    exit(1)

evalscript = """
//VERSION=3
function setup() {
  return {
    input: ["B08", "B04"],
    output: {
      id: "default",
      bands: 1,
      sampleType: "FLOAT32"
    }
  };
}

function evaluatePixel(sample) {
  let ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04 + 0.0001);
  return [ndvi];
}
"""

payload = {
    "input": {
        "bounds": {
            "bbox": [8682920.28, 2875744.62, 8694052.23, 2888032.38],
            "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/3857"}
        },
        "data": [
            {
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": "2024-01-01T00:00:00Z",
                        "to": "2024-02-01T00:00:00Z"
                    },
                    "maxCloudCoverage": 20
                }
            }
        ]
    },
    "output": {
        "width": 512,
        "height": 512,
        "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]
    },
    "evalscript": evalscript
}

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

response = requests.post(API_URL, headers=headers, json=payload)
if response.status_code == 200:
    with open("ndvi_output.tiff", "wb") as f:
        f.write(response.content)
    print("NDVI TIFF saved successfully.")
else:
    print(f"Error: {response.status_code} - {response.text}")
