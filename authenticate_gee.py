import ee

# Authenticate and initialize Google Earth Engine
try:
    ee.Authenticate()
    ee.Initialize(project='boxwood-well-512915-r3')
    print("Google Earth Engine authenticated and initialized successfully!")
    
    # Test with a simple query
    image = ee.Image('COPERNICUS/S2_SR/20230601T052839_20230601T054343_T43PCT')
    print("Test successful - GEE is working!")
    
except Exception as e:
    print(f"Error: {e}")
    print("Please visit: https://code.earthengine.google.com/ and sign up first")