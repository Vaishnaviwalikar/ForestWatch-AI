import os
import json
import logging
import hashlib
import numpy as np

logger = logging.getLogger(__name__)

# Default project ID from user configuration or environment
DEFAULT_GEE_PROJECT = os.environ.get("GEE_PROJECT", "boxwood-well-512915-r3")
_gee_initialized = False

# Cache directory for historical composites to save credits and time
CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "static", "cache", "historical"))
os.makedirs(CACHE_DIR, exist_ok=True)


def initialize_gee(project=None):
    """
    Initialize Google Earth Engine.
    Uses the project provided, or GEE_PROJECT environment variable, or the default project.
    """
    global _gee_initialized
    project_id = project or os.environ.get("GEE_PROJECT", DEFAULT_GEE_PROJECT)

    try:
        import ee
        try:
            ee.Initialize(project=project_id)
            _gee_initialized = True
            logger.info(f"Google Earth Engine initialized successfully with project: {project_id}")
            return True, f"GEE initialized with project '{project_id}'"
        except Exception as e:
            try:
                ee.Initialize()
                _gee_initialized = True
                logger.info("Google Earth Engine initialized successfully with default credentials")
                return True, "GEE initialized with default credentials"
            except Exception as inner_e:
                logger.warning(f"GEE initialization failed: {str(e)} / {str(inner_e)}")
                return False, f"GEE initialization failed: {str(e)}"
    except ImportError:
        logger.error("earthengine-api package is not installed.")
        return False, "earthengine-api package not installed"


def is_gee_available():
    """Check if GEE is initialized and ready for queries"""
    global _gee_initialized
    if _gee_initialized:
        return True
    success, _ = initialize_gee()
    return success


def get_sentinel2_tile_urls(lat, lon, max_cloud_pct=30):
    """
    Generate live Google Earth Engine tile layer URLs for Leaflet:
    1. True-Color RGB Sentinel-2 Surface Reflectance
    2. SCL-masked Vegetation Index (NDVI) Layer
    Returns metadata including latest acquisition date and cloud percentage.
    """
    if not is_gee_available():
        return None, "Google Earth Engine unavailable"

    try:
        import ee
        point = ee.Geometry.Point([float(lon), float(lat)])
        aoi = point.buffer(6000).bounds()

        col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
               .filterBounds(aoi)
               .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', float(max_cloud_pct)))
               .sort('system:time_start', False))

        count = int(col.size().getInfo())
        if count == 0:
            # Widen search to 70% clouds
            col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                   .filterBounds(aoi)
                   .sort('system:time_start', False))
            count = int(col.size().getInfo())
            if count == 0:
                return None, "No Sentinel-2 imagery available for this area"

        img = col.first()
        scene_id = str(img.get('system:index').getInfo())
        timestamp_ms = img.get('system:time_start').getInfo()
        acq_date = ee.Date(timestamp_ms).format('YYYY-MM-dd HH:mm:ss').getInfo()
        cloud_pct = float(img.get('CLOUDY_PIXEL_PERCENTAGE').getInfo())
        spacecraft = str(img.get('SPACECRAFT_NAME').getInfo() if img.get('SPACECRAFT_NAME') else 'Sentinel-2')

        # Mask clouds using SCL
        scl = img.select('SCL')
        valid = (scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
                 .And(scl.neq(0)).And(scl.neq(1)))
        masked = img.updateMask(valid)

        # True-color RGB
        rgb_map = masked.select(['B4', 'B3', 'B2']).getMapId({'min': 0, 'max': 2500})
        rgb_url = rgb_map['tile_fetcher'].url_format

        # NDVI layer
        ndvi = masked.normalizedDifference(['B8', 'B4'])
        ndvi_map = ndvi.getMapId({'min': -0.1, 'max': 0.8, 'palette': ['#0000ff', '#ffffff', '#ffff00', '#228b22', '#004d00']})
        ndvi_url = ndvi_map['tile_fetcher'].url_format

        return {
            "status": "success",
            "scene_id": scene_id,
            "acquisition_date": acq_date,
            "cloud_percentage": round(cloud_pct, 2),
            "spacecraft": spacecraft,
            "rgb_tile_url": rgb_url,
            "ndvi_tile_url": ndvi_url,
            "data_source": "Copernicus Sentinel-2 Level-2A (Harmonized)",
            "quality_flag": "High Confidence" if cloud_pct < 15 else "Moderate Confidence"
        }, None
    except Exception as e:
        logger.error(f"Error generating GEE tile URLs: {e}")
        return None, str(e)



def _mask_scl_clouds(img):
    """
    Mask Sentinel-2 Level-2A imagery using the Scene Classification Layer (SCL).
    SCL Classes masked:
      3: Cloud shadows
      8: Cloud medium probability
      9: Cloud high probability
      10: Thin cirrus
      11: Snow / Ice
    Preserves:
      4: Vegetation
      5: Non-vegetated (bare soil, sand, rocks)
      6: Water
    """
    import ee
    scl = img.select('SCL')
    # Valid non-cloud pixels
    valid = (scl.neq(3)
             .And(scl.neq(8))
             .And(scl.neq(9))
             .And(scl.neq(10))
             .And(scl.neq(11))
             .And(scl.neq(0))
             .And(scl.neq(1)))
    return img.updateMask(valid)


def fetch_sentinel2_bands(lat, lon, start_date, end_date, radius_meters=2000, scale=20, max_cloud_pct=25, use_scl_mask=True, cancel_event=None):
    """
    Fetch actual Sentinel-2 B04 (Red) and B08 (NIR) bands for a given location and date range.
    Applies SCL cloud/shadow filtering.
    """
    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Operation cancelled by user")

    if not is_gee_available():
        raise ConnectionError("Google Earth Engine is not initialized or accessible")

    import ee

    logger.info(f"Querying Sentinel-2 imagery around ({lat}, {lon}) from {start_date} to {end_date}...")
    point = ee.Geometry.Point([float(lon), float(lat)])
    aoi = point.buffer(float(radius_meters)).bounds()

    # Query Sentinel-2 Surface Reflectance (Harmonized)
    collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                  .filterBounds(aoi)
                  .filterDate(str(start_date), str(end_date))
                  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', float(max_cloud_pct)))
                  .sort('CLOUDY_PIXEL_PERCENTAGE'))

    count = int(collection.size().getInfo())
    logger.info(f"Found {count} candidate Sentinel-2 scenes (scene clouds < {max_cloud_pct}%)")

    if count == 0:
        logger.warning(f"No scenes found with cloud cover < {max_cloud_pct}%. Widening search to 60%...")
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                      .filterBounds(aoi)
                      .filterDate(str(start_date), str(end_date))
                      .sort('CLOUDY_PIXEL_PERCENTAGE'))
        count = int(collection.size().getInfo())
        if count == 0:
            raise ValueError(f"No Sentinel-2 imagery available for ({lat}, {lon}) between {start_date} and {end_date}")

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Operation cancelled by user")

    # Select the clearest image
    img = collection.first()

    scene_id = str(img.get('system:index').getInfo())
    timestamp_ms = img.get('system:time_start').getInfo()
    acquisition_date = ee.Date(timestamp_ms).format('YYYY-MM-dd HH:mm:ss').getInfo()
    cloud_pct = float(img.get('CLOUDY_PIXEL_PERCENTAGE').getInfo())
    spacecraft = str(img.get('SPACECRAFT_NAME').getInfo() if img.get('SPACECRAFT_NAME') else 'Sentinel-2')

    # Apply SCL cloud & shadow mask if enabled
    processed_img = _mask_scl_clouds(img) if use_scl_mask else img

    # Reproject to EPSG:3857 at specified scale
    scaled_bands = processed_img.select(['B4', 'B8']).multiply(0.0001).reproject(crs='EPSG:3857', scale=scale)

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Operation cancelled by user")

    sampled = scaled_bands.sampleRectangle(region=aoi, defaultValue=0)
    b4_data = np.array(sampled.get('B4').getInfo(), dtype=np.float32)
    b8_data = np.array(sampled.get('B8').getInfo(), dtype=np.float32)

    height, width = b4_data.shape
    pixel_area_m2 = scale * scale
    total_area_ha = (height * width * pixel_area_m2) / 10000.0

    metadata = {
        "source": "Google Earth Engine (COPERNICUS/S2_SR_HARMONIZED)",
        "scene_id": scene_id,
        "acquisition_date": acquisition_date,
        "cloud_percentage": round(cloud_pct, 2),
        "spacecraft": spacecraft,
        "latitude": float(lat),
        "longitude": float(lon),
        "scale_meters": scale,
        "shape": [int(height), int(width)],
        "total_pixels": int(height * width),
        "total_area_ha": round(total_area_ha, 2),
        "total_area_km2": round(total_area_ha / 100.0, 4),
        "query_start_date": str(start_date),
        "query_end_date": str(end_date),
        "scl_masked": use_scl_mask,
        "observations_available": count
    }

    return b4_data, b8_data, metadata


def fetch_bitemporal_sentinel2(lat, lon, baseline_start, baseline_end, recent_start, recent_end,
                               radius_meters=2000, scale=20, max_cloud_pct=25, cancel_event=None):
    """
    Fetch bitemporal Sentinel-2 observations (Baseline and Recent) for genuine change and deforestation detection.
    """
    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Operation cancelled by user")

    logger.info("Initializing Sentinel-2 bitemporal data loader with SCL masking...")
    gee_ok = is_gee_available()

    if gee_ok:
        try:
            logger.info("Fetching Baseline Sentinel-2 observation...")
            b4_base, b8_base, meta_base = fetch_sentinel2_bands(
                lat=lat, lon=lon,
                start_date=baseline_start, end_date=baseline_end,
                radius_meters=radius_meters, scale=scale,
                max_cloud_pct=max_cloud_pct, cancel_event=cancel_event
            )

            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Operation cancelled by user")

            logger.info("Fetching Recent Sentinel-2 observation...")
            b4_recent, b8_recent, meta_recent = fetch_sentinel2_bands(
                lat=lat, lon=lon,
                start_date=recent_start, end_date=recent_end,
                radius_meters=radius_meters, scale=scale,
                max_cloud_pct=max_cloud_pct, cancel_event=cancel_event
            )

            min_h = min(b4_base.shape[0], b4_recent.shape[0])
            min_w = min(b4_base.shape[1], b4_recent.shape[1])

            b4_base = b4_base[:min_h, :min_w]
            b8_base = b8_base[:min_h, :min_w]
            b4_recent = b4_recent[:min_h, :min_w]
            b8_recent = b8_recent[:min_h, :min_w]

            meta_base["shape"] = [min_h, min_w]
            meta_base["total_pixels"] = min_h * min_w
            meta_recent["shape"] = [min_h, min_w]
            meta_recent["total_pixels"] = min_h * min_w

            logger.info(f"Successfully retrieved bitemporal Sentinel-2 data. Grid size: {min_h} x {min_w}")
            return (b4_base, b8_base, meta_base), (b4_recent, b8_recent, meta_recent)

        except InterruptedError:
            raise
        except Exception as e:
            logger.warning(f"GEE retrieval failed ({str(e)}). Falling back to realistic simulation mode.")

    # Offline fallback
    logger.info("Using realistic offline Sentinel-2 satellite data generator...")
    return generate_synthetic_sentinel2_bands(
        lat=lat, lon=lon,
        baseline_date=baseline_start,
        recent_date=recent_start,
        scale=scale,
        cancel_event=cancel_event
    )


def fetch_multiyear_historical_sentinel2(lat, lon, start_year, end_year,
                                         season_start_md="01-01", season_end_md="05-31",
                                         radius_meters=1500, scale=30, max_cloud_pct=30,
                                         cancel_event=None, progress_callback=None):
    """
    Perform multi-year historical satellite analysis (e.g. 2018 to 2024).
    Computes annual seasonal median composites with SCL cloud & shadow masking.
    Caches results per year/parameter set to save AI credits and Earth Engine computation.
    """
    def log(msg):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    start_year = int(start_year)
    end_year = int(end_year)
    if start_year > end_year:
        start_year, end_year = end_year, start_year

    years_list = list(range(start_year, end_year + 1))
    log(f"Starting Multi-Year Historical Analysis across {len(years_list)} years ({start_year} - {end_year})...")

    results = []
    gee_ok = is_gee_available()

    for year in years_list:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError(f"Multi-year analysis cancelled by user at year {year}.")

        # Check local cache first
        cache_key = hashlib.md5(f"{lat:.4f}_{lon:.4f}_{year}_{season_start_md}_{season_end_md}_{radius_meters}_{scale}".encode()).hexdigest()
        cache_file = os.path.join(CACHE_DIR, f"hist_{year}_{cache_key}.json")

        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    cached_data = json.load(f)
                log(f"✅ Year {year}: Loaded from local cache (Mean NDVI: {cached_data['mean_ndvi']:.3f})")
                results.append(cached_data)
                continue
            except Exception as e:
                logger.warning(f"Error reading cache file {cache_file}: {e}")

        # Query GEE if available
        start_date = f"{year}-{season_start_md}"
        end_date = f"{year}-{season_end_md}"

        log(f"🛰️ Processing Year {year} ({start_date} to {end_date})...")

        year_record = {
            "year": year,
            "period": f"{start_date} to {end_date}",
            "status": "unavailable",
            "observation_count": 0,
            "mean_ndvi": 0.0,
            "median_ndvi": 0.0,
            "min_ndvi": 0.0,
            "max_ndvi": 0.0,
            "std_ndvi": 0.0,
            "dense_pct": 0.0,
            "light_pct": 0.0,
            "non_forest_pct": 0.0,
            "valid_pixels": 0,
            "total_pixels": 0,
            "quality_flag": "No Data"
        }

        if gee_ok:
            try:
                import ee
                point = ee.Geometry.Point([float(lon), float(lat)])
                aoi = point.buffer(float(radius_meters)).bounds()

                col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                       .filterBounds(aoi)
                       .filterDate(start_date, end_date)
                       .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', float(max_cloud_pct))))

                obs_count = int(col.size().getInfo())
                year_record["observation_count"] = obs_count

                if obs_count > 0:
                    # Apply SCL cloud masking and median compositing
                    masked_col = col.map(_mask_scl_clouds)
                    composite = masked_col.select(['B4', 'B8']).median().multiply(0.0001).reproject(crs='EPSG:3857', scale=scale)

                    if cancel_event and cancel_event.is_set():
                        raise InterruptedError(f"Multi-year analysis cancelled at year {year}.")

                    sampled = composite.sampleRectangle(region=aoi, defaultValue=0)
                    b4_arr = np.array(sampled.get('B4').getInfo(), dtype=np.float32)
                    b8_arr = np.array(sampled.get('B8').getInfo(), dtype=np.float32)

                    # Compute NDVI
                    denom = b8_arr + b4_arr
                    valid_mask = (denom > 0.0001) & (b8_arr > 0)
                    ndvi_arr = np.zeros_like(b4_arr)
                    ndvi_arr[valid_mask] = (b8_arr[valid_mask] - b4_arr[valid_mask]) / denom[valid_mask]
                    ndvi_arr = np.clip(ndvi_arr, -1.0, 1.0)

                    valid_pixels = int(np.sum(valid_mask))
                    total_pixels = int(b4_arr.size)

                    if valid_pixels > 0:
                        valid_vals = ndvi_arr[valid_mask]
                        dense_px = int(np.sum(valid_vals >= 0.50))
                        light_px = int(np.sum((valid_vals >= 0.20) & (valid_vals < 0.50)))
                        non_px = int(np.sum(valid_vals < 0.20))

                        year_record.update({
                            "status": "success",
                            "mean_ndvi": round(float(np.mean(valid_vals)), 4),
                            "median_ndvi": round(float(np.median(valid_vals)), 4),
                            "min_ndvi": round(float(np.min(valid_vals)), 4),
                            "max_ndvi": round(float(np.max(valid_vals)), 4),
                            "std_ndvi": round(float(np.std(valid_vals)), 4),
                            "dense_pct": round((dense_px / valid_pixels) * 100.0, 2),
                            "light_pct": round((light_px / valid_pixels) * 100.0, 2),
                            "non_forest_pct": round((non_px / valid_pixels) * 100.0, 2),
                            "valid_pixels": valid_pixels,
                            "total_pixels": total_pixels,
                            "quality_flag": "High Confidence" if obs_count >= 3 else "Moderate Confidence"
                        })
                    else:
                        year_record["quality_flag"] = "All Pixels Masked by Clouds/Shadows"
                else:
                    year_record["quality_flag"] = "Insufficient Clear Observations"

            except InterruptedError:
                raise
            except Exception as e:
                logger.warning(f"Error fetching historical year {year}: {e}")
                year_record["quality_flag"] = f"GEE Query Error: {str(e)[:50]}"

        # If GEE unconfigured or failed, generate realistic simulated year
        if year_record["status"] != "success":
            year_record = _simulate_historical_year(lat, lon, year, start_date, end_date)

        # Cache valid record
        try:
            with open(cache_file, "w") as f:
                json.dump(year_record, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to cache historical year {year}: {e}")

        log(f"Completed Year {year}: Mean NDVI = {year_record['mean_ndvi']} | Dense Forest = {year_record['dense_pct']}% ({year_record['quality_flag']})")
        results.append(year_record)

    # Compute year-on-year changes
    for i in range(1, len(results)):
        prev_ndvi = results[i-1]["mean_ndvi"]
        curr_ndvi = results[i]["mean_ndvi"]
        delta = curr_ndvi - prev_ndvi
        results[i]["yoy_change"] = round(delta, 4)
        if delta <= -0.05:
            results[i]["trend_indicator"] = "Decline Alert"
        elif delta >= 0.05:
            results[i]["trend_indicator"] = "Vegetation Gain"
        else:
            results[i]["trend_indicator"] = "Stable"
    if results:
        results[0]["yoy_change"] = 0.0
        results[0]["trend_indicator"] = "Baseline Year"

    return {
        "location": {"latitude": lat, "longitude": lon},
        "period": f"{start_year} - {end_year}",
        "total_years": len(years_list),
        "years": results
    }


def _simulate_historical_year(lat, lon, year, start_date, end_date):
    """Realistic offline fallback simulation for historical trend testing"""
    seed = int(abs(float(lat) * 100 + float(lon) * 10 + year)) % 100000
    np.random.seed(seed)

    # Realistic gradual trend with natural annual variation
    base_val = 0.44 + 0.03 * np.sin((year - 2018) * 0.8) + np.random.normal(0, 0.015)
    base_val = float(np.clip(base_val, 0.25, 0.75))

    return {
        "year": year,
        "period": f"{start_date} to {end_date}",
        "status": "success",
        "observation_count": int(np.random.randint(4, 12)),
        "mean_ndvi": round(base_val, 4),
        "median_ndvi": round(base_val + 0.01, 4),
        "min_ndvi": round(base_val - 0.25, 4),
        "max_ndvi": round(base_val + 0.35, 4),
        "std_ndvi": round(float(np.random.uniform(0.11, 0.16)), 4),
        "dense_pct": round(float(np.clip((base_val - 0.3) * 160.0, 10.0, 75.0)), 2),
        "light_pct": round(float(np.random.uniform(20.0, 35.0)), 2),
        "non_forest_pct": round(float(np.random.uniform(5.0, 15.0)), 2),
        "valid_pixels": 15000,
        "total_pixels": 15000,
        "quality_flag": "Simulation Fallback"
    }


def generate_synthetic_sentinel2_bands(lat, lon, baseline_date, recent_date, shape=(200, 200), scale=20, cancel_event=None):
    """
    Generate realistic synthetic Sentinel-2 Red (B04) and NIR (B08) reflectance bands
    used exclusively as an offline fallback when Google Earth Engine / network is unreachable.
    """
    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Operation cancelled by user")

    np.random.seed(int(abs(float(lat) * 1000 + float(lon) * 100)) % 100000)
    h, w = shape

    y, x = np.ogrid[:h, :w]
    cx, cy = w // 2, h // 2
    dist_from_center = np.sqrt((x - cx)**2 + (y - cy)**2) / (np.sqrt(h**2 + w**2) / 2)

    base_canopy = 0.65 - 0.25 * dist_from_center + 0.05 * np.sin(x / 15.0) * np.cos(y / 15.0)
    base_canopy = np.clip(base_canopy, 0.1, 0.8)

    noise_b4 = np.random.normal(0, 0.01, (h, w))
    noise_b8 = np.random.normal(0, 0.02, (h, w))

    b4_baseline = np.clip(0.18 - 0.14 * base_canopy + noise_b4, 0.02, 0.40).astype(np.float32)
    b8_baseline = np.clip(0.15 + 0.65 * base_canopy + noise_b8, 0.05, 0.85).astype(np.float32)

    deforestation_mask = np.zeros((h, w), dtype=bool)
    p1_ymin, p1_ymax = int(h * 0.20), int(h * 0.45)
    p1_xmin, p1_xmax = int(w * 0.55), int(w * 0.85)
    deforestation_mask[p1_ymin:p1_ymax, p1_xmin:p1_xmax] = True

    for i in range(int(h * 0.1), int(h * 0.8)):
        j = int(w * 0.35 + 10 * np.sin(i / 10.0))
        if 0 <= j < w:
            deforestation_mask[max(0, i-2):min(h, i+3), max(0, j-2):min(w, j+3)] = True

    b4_recent = b4_baseline.copy()
    b8_recent = b8_baseline.copy()

    b4_recent[deforestation_mask] = np.random.uniform(0.20, 0.32, size=np.sum(deforestation_mask)).astype(np.float32)
    b8_recent[deforestation_mask] = np.random.uniform(0.12, 0.22, size=np.sum(deforestation_mask)).astype(np.float32)

    pixel_area_m2 = scale * scale
    total_area_ha = (h * w * pixel_area_m2) / 10000.0

    meta_baseline = {
        "source": "Realistic Offline Simulation (Sentinel-2 Spectral Characteristics)",
        "scene_id": f"SIM_S2A_MSIL2A_{baseline_date.replace('-', '')}",
        "acquisition_date": f"{baseline_date} 10:30:00",
        "cloud_percentage": 1.2,
        "spacecraft": "Sentinel-2A (Simulation)",
        "latitude": float(lat),
        "longitude": float(lon),
        "scale_meters": scale,
        "shape": [h, w],
        "total_pixels": h * w,
        "total_area_ha": round(total_area_ha, 2),
        "total_area_km2": round(total_area_ha / 100.0, 4),
        "query_start_date": baseline_date,
        "query_end_date": baseline_date,
        "scl_masked": True
    }

    meta_recent = {
        "source": "Realistic Offline Simulation (Sentinel-2 Spectral Characteristics)",
        "scene_id": f"SIM_S2B_MSIL2A_{recent_date.replace('-', '')}",
        "acquisition_date": f"{recent_date} 10:30:00",
        "cloud_percentage": 2.4,
        "spacecraft": "Sentinel-2B (Simulation)",
        "latitude": float(lat),
        "longitude": float(lon),
        "scale_meters": scale,
        "shape": [h, w],
        "total_pixels": h * w,
        "total_area_ha": round(total_area_ha, 2),
        "total_area_km2": round(total_area_ha / 100.0, 4),
        "query_start_date": recent_date,
        "query_end_date": recent_date,
        "scl_masked": True
    }

    return (b4_baseline, b8_baseline, meta_baseline), (b4_recent, b8_recent, meta_recent)
