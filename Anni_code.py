import os
import sys
import json
import csv
import logging
import traceback
import smtplib
import shutil
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from fpdf import FPDF

# Import GEE data loader
import gee_data_loader

logger = logging.getLogger(__name__)

# Base output directory
BASE_OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "static", "sentinel_output"))
os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)

# Validated NDVI scientific thresholds
NDVI_NON_FOREST_MAX = 0.20   # Bare ground, water, built-up, sparse rock
NDVI_LIGHT_FOREST_MAX = 0.50 # Light / sparse vegetation, shrubs, degraded forest
# NDVI >= 0.50 is Dense Forest canopy cover

# Deforestation detection thresholds
DEFORESTATION_DELTA_THRESHOLD = -0.15 # Minimum drop in NDVI to indicate vegetation loss
REGROWTH_DELTA_THRESHOLD = +0.15       # Minimum increase in NDVI to indicate vegetation gain


def get_email_config():
    """Retrieve email credentials from environment variables securely"""
    return {
        "sender": os.environ.get("EMAIL_SENDER", "").strip(),
        "password": os.environ.get("EMAIL_PASSWORD", "").strip(),
        "recipient": os.environ.get("EMAIL_RECIPIENT", "").strip(),
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com").strip(),
        "port": int(os.environ.get("SMTP_PORT", "465")),
        "subject": os.environ.get("EMAIL_SUBJECT", "ForestWatch AI — Forest & Deforestation Report")
    }


def clean_pdf_text(text):
    """Normalize text to Latin-1 compatible characters for FPDF"""
    if not text:
        return ""
    replacements = {
        '—': '-', '–': '-', '’': "'", '‘': "'", '“': '"', '”': '"',
        'Δ': 'Delta ', '²': '2', '³': '3', '°': ' deg', 'µ': 'u',
        '•': '*', '…': '...'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode('latin-1', 'replace').decode('latin-1')


def calculate_ndvi(red_band, nir_band):
    """
    Calculate Normalized Difference Vegetation Index (NDVI).
    NDVI = (NIR - Red) / (NIR + Red)
    Valid pixels: finite, valid surface reflectance (> 0.0 and <= 2.0), and non-zero denominator (> 1e-4).
    Missing, cloudy, shadowed, or zero-filled pixels are set to NaN so they never distort statistics.
    """
    red = np.asarray(red_band, dtype=np.float32)
    nir = np.asarray(nir_band, dtype=np.float32)

    # 1. Finite numbers (no NaN or Inf)
    finite_mask = np.isfinite(red) & np.isfinite(nir)

    # 2. Valid surface reflectance (excluding nodata <= 0, e.g. GEE defaultValue=0 or -9999, and out-of-range > 2.0)
    valid_refl = (red > 0.0) & (nir > 0.0) & (red <= 2.0) & (nir <= 2.0)

    # 3. Non-zero denominator: |NIR + Red| > 1e-4
    denominator = nir + red
    valid_denom = np.abs(denominator) > 0.0001

    valid_mask = finite_mask & valid_refl & valid_denom

    ndvi = np.full_like(red, np.nan, dtype=np.float32)
    ndvi[valid_mask] = np.clip((nir[valid_mask] - red[valid_mask]) / denominator[valid_mask], -1.0, 1.0)
    return ndvi


def classify_single_epoch(ndvi_array):
    """
    Classify forest cover for a single date based on peer-reviewed NDVI thresholds.
    Invalid pixels (NaN) are strictly excluded from the analyzed denominator.
    """
    valid_mask = ~np.isnan(ndvi_array) & np.isfinite(ndvi_array)
    total_valid = int(np.sum(valid_mask))
    total_pixels = int(ndvi_array.size)

    if total_valid == 0:
        return np.full_like(ndvi_array, 255, dtype=np.uint8), {
            "total_pixels": total_pixels,
            "total_valid_pixels": 0,
            "masked_pixels": total_pixels,
            "valid_data_pct": 0.0,
            "dense_pixels": 0, "light_pixels": 0, "non_forest_pixels": 0,
            "dense_pct": 0.0, "light_pct": 0.0, "non_forest_pct": 0.0,
            "mean_ndvi": None, "std_ndvi": None, "min_ndvi": None, "max_ndvi": None
        }

    dense_mask = valid_mask & (ndvi_array >= NDVI_LIGHT_FOREST_MAX)
    light_mask = valid_mask & (ndvi_array >= NDVI_NON_FOREST_MAX) & (ndvi_array < NDVI_LIGHT_FOREST_MAX)
    non_forest_mask = valid_mask & (ndvi_array < NDVI_NON_FOREST_MAX)

    dense_count = int(np.sum(dense_mask))
    light_count = int(np.sum(light_mask))
    non_forest_count = int(np.sum(non_forest_mask))

    class_map = np.full_like(ndvi_array, 255, dtype=np.uint8)  # 255 = Masked / Invalid
    class_map[non_forest_mask] = 0
    class_map[light_mask] = 1
    class_map[dense_mask] = 2

    valid_vals = ndvi_array[valid_mask]

    stats = {
        "total_pixels": total_pixels,
        "total_valid_pixels": total_valid,
        "masked_pixels": int(total_pixels - total_valid),
        "valid_data_pct": round((total_valid / total_pixels) * 100.0, 2) if total_pixels > 0 else 0.0,
        "dense_pixels": dense_count,
        "light_pixels": light_count,
        "non_forest_pixels": non_forest_count,
        "dense_pct": round((dense_count / total_valid) * 100.0, 2),
        "light_pct": round((light_count / total_valid) * 100.0, 2),
        "non_forest_pct": round((non_forest_count / total_valid) * 100.0, 2),
        "mean_ndvi": round(float(np.mean(valid_vals)), 4),
        "std_ndvi": round(float(np.std(valid_vals)), 4),
        "min_ndvi": round(float(np.min(valid_vals)), 4),
        "max_ndvi": round(float(np.max(valid_vals)), 4)
    }
    return class_map, stats


def detect_deforestation(ndvi_baseline, ndvi_recent, meta_baseline, meta_recent):
    """
    Genuine multi-temporal vegetation change detection.
    Compares two satellite observations (Baseline vs Recent) strictly over an explicitly defined comparison mask.
    Invalid, missing, cloudy, or shadowed pixels are strictly excluded from change statistics and area calculations.
    """
    valid_base = ~np.isnan(ndvi_baseline) & np.isfinite(ndvi_baseline)
    valid_recent = ~np.isnan(ndvi_recent) & np.isfinite(ndvi_recent)
    comparison_mask = valid_base & valid_recent
    total_valid = int(np.sum(comparison_mask))
    total_pixels = int(ndvi_baseline.size)

    delta_ndvi = np.full_like(ndvi_baseline, np.nan, dtype=np.float32)
    delta_ndvi[comparison_mask] = ndvi_recent[comparison_mask] - ndvi_baseline[comparison_mask]

    scale = meta_recent.get("scale_meters", 20)
    pixel_area_ha = (scale * scale) / 10000.0

    if total_valid == 0:
        change_map = np.full_like(ndvi_baseline, 255, dtype=np.uint8)
        change_stats = {
            "total_pixels": total_pixels,
            "total_valid_pixels": 0,
            "masked_pixels": total_pixels,
            "valid_data_pct": 0.0,
            "pixel_resolution_m": scale,
            "total_area_ha": 0.0,
            "total_area_km2": 0.0,
            "mean_delta_ndvi": 0.0,
            "deforested": {"label": "Potential Vegetation Loss", "pixels": 0, "hectares": 0.0, "km2": 0.0, "percentage": 0.0},
            "regrowth": {"label": "Vegetation Recovery / Gain", "pixels": 0, "hectares": 0.0, "km2": 0.0, "percentage": 0.0},
            "stable_dense": {"label": "Stable Dense Canopy", "pixels": 0, "hectares": 0.0, "km2": 0.0, "percentage": 0.0},
            "stable_light": {"label": "Stable Light Canopy", "pixels": 0, "hectares": 0.0, "km2": 0.0, "percentage": 0.0},
            "non_forest": {"label": "Persistent Non-Forest", "pixels": 0, "hectares": 0.0, "km2": 0.0, "percentage": 0.0},
            "risk_level": "Insufficient Data (Cloud / Shadow Masked)"
        }
        return change_map, delta_ndvi, change_stats

    was_forest = comparison_mask & (ndvi_baseline >= 0.40)
    was_non_forest = comparison_mask & (ndvi_baseline < 0.30)

    # 1. Potential Vegetation Loss: was forest, and experienced significant vegetative drop
    deforested_mask = was_forest & (delta_ndvi <= DEFORESTATION_DELTA_THRESHOLD)

    # 2. Vegetation Gain / Recovery: was non-forest or degraded, and NDVI significantly gained
    regrowth_mask = was_non_forest & (delta_ndvi >= REGROWTH_DELTA_THRESHOLD) & (ndvi_recent >= 0.40)

    # 3. Stable Dense Forest
    stable_dense_mask = comparison_mask & (ndvi_baseline >= NDVI_LIGHT_FOREST_MAX) & (ndvi_recent >= NDVI_LIGHT_FOREST_MAX) & ~deforested_mask

    # 4. Stable Light Forest
    stable_light_mask = comparison_mask & (ndvi_recent >= NDVI_NON_FOREST_MAX) & (ndvi_recent < NDVI_LIGHT_FOREST_MAX) & ~deforested_mask & ~regrowth_mask & ~stable_dense_mask

    # 5. Persistent Non-Forest / Other
    non_forest_mask = comparison_mask & ~deforested_mask & ~regrowth_mask & ~stable_dense_mask & ~stable_light_mask

    change_map = np.full_like(ndvi_baseline, 255, dtype=np.uint8)  # 255 = Masked / Invalid
    change_map[non_forest_mask] = 0
    change_map[stable_light_mask] = 1
    change_map[stable_dense_mask] = 2
    change_map[deforested_mask] = 3
    change_map[regrowth_mask] = 4

    deforested_pixels = int(np.sum(deforested_mask))
    regrowth_pixels = int(np.sum(regrowth_mask))
    stable_dense_pixels = int(np.sum(stable_dense_mask))
    stable_light_pixels = int(np.sum(stable_light_mask))
    non_forest_pixels = int(np.sum(non_forest_mask))

    deforested_ha = round(deforested_pixels * pixel_area_ha, 2)
    regrowth_ha = round(regrowth_pixels * pixel_area_ha, 2)
    stable_dense_ha = round(stable_dense_pixels * pixel_area_ha, 2)
    stable_light_ha = round(stable_light_pixels * pixel_area_ha, 2)
    non_forest_ha = round(non_forest_pixels * pixel_area_ha, 2)
    total_valid_ha = round(total_valid * pixel_area_ha, 2)

    deforest_pct = round((deforested_pixels / total_valid * 100.0), 2)
    regrowth_pct = round((regrowth_pixels / total_valid * 100.0), 2)
    stable_dense_pct = round((stable_dense_pixels / total_valid * 100.0), 2)
    stable_light_pct = round((stable_light_pixels / total_valid * 100.0), 2)
    non_forest_pct = round((non_forest_pixels / total_valid * 100.0), 2)

    if total_valid < (total_pixels * 0.05):
        severity = "Insufficient Valid Observations (Heavy Cloud Cover)"
    elif deforest_pct >= 10.0 or deforested_ha >= 60.0:
        severity = "Critical Alert (Potential Severe Canopy Loss)"
    elif deforest_pct >= 3.0 or deforested_ha >= 25.0:
        severity = "High Alert (Potential Canopy Disturbance)"
    elif deforest_pct >= 1.0 or deforested_ha >= 5.0:
        severity = "Moderate Alert (Potential Canopy Thinning)"
    elif deforest_pct > 0.1:
        severity = "Low Alert (Minor Localized Shift)"
    else:
        severity = "Minimal / Stable"

    valid_deltas = delta_ndvi[comparison_mask]

    change_stats = {
        "total_pixels": total_pixels,
        "total_valid_pixels": total_valid,
        "masked_pixels": int(total_pixels - total_valid),
        "valid_data_pct": round((total_valid / total_pixels) * 100.0, 2) if total_pixels > 0 else 0.0,
        "pixel_resolution_m": scale,
        "total_area_ha": total_valid_ha,
        "total_area_km2": round(total_valid_ha / 100.0, 4),
        "mean_delta_ndvi": round(float(np.mean(valid_deltas)), 4) if len(valid_deltas) > 0 else 0.0,
        "deforested": {
            "label": "Potential Vegetation Loss",
            "pixels": deforested_pixels,
            "hectares": deforested_ha,
            "km2": round(deforested_ha / 100.0, 4),
            "percentage": deforest_pct
        },
        "regrowth": {
            "label": "Vegetation Recovery / Gain",
            "pixels": regrowth_pixels,
            "hectares": regrowth_ha,
            "km2": round(regrowth_ha / 100.0, 4),
            "percentage": regrowth_pct
        },
        "stable_dense": {
            "label": "Stable Dense Canopy",
            "pixels": stable_dense_pixels,
            "hectares": stable_dense_ha,
            "km2": round(stable_dense_ha / 100.0, 4),
            "percentage": stable_dense_pct
        },
        "stable_light": {
            "label": "Stable Light Canopy",
            "pixels": stable_light_pixels,
            "hectares": stable_light_ha,
            "km2": round(stable_light_ha / 100.0, 4),
            "percentage": stable_light_pct
        },
        "non_forest": {
            "label": "Persistent Non-Forest",
            "pixels": non_forest_pixels,
            "hectares": non_forest_ha,
            "km2": round(non_forest_ha / 100.0, 4),
            "percentage": non_forest_pct
        },
        "risk_level": severity
    }

    min_delta = float(np.nanmin(valid_deltas)) if len(valid_deltas) > 0 else 0.0
    max_delta = float(np.nanmax(valid_deltas)) if len(valid_deltas) > 0 else 0.0
    logger.info(
        f"[MAP DIAGNOSTIC] Layer: Multi-Temporal Canopy Change (ΔNDVI) | "
        f"Valid Pixels: {total_valid:,} / {total_pixels:,} ({change_stats['valid_data_pct']}%) | "
        f"Masked Pixels: {total_pixels - total_valid:,} | "
        f"ΔNDVI Range: [{min_delta:+.4f}, {max_delta:+.4f}] (Mean: {change_stats['mean_delta_ndvi']:+.4f}) | "
        f"Class Distribution: Loss={deforested_pixels} ({deforest_pct}%), Regrowth={regrowth_pixels} ({regrowth_pct}%), "
        f"Dense={stable_dense_pixels} ({stable_dense_pct}%), Light={stable_light_pixels} ({stable_light_pct}%), "
        f"Non-Forest={non_forest_pixels} ({non_forest_pct}%), Masked={total_pixels - total_valid}"
    )

    return change_map, delta_ndvi, change_stats


def generate_comprehensive_report(output_dir, analysis_id, meta_baseline, meta_recent,
                                  base_stats, recent_stats, change_stats):
    """
    Generate an exhaustive, data-driven remote sensing analysis report.
    """
    report_filename = f"forest_analysis_{analysis_id}.txt"
    report_path = os.path.join(output_dir, report_filename)
    latest_path = os.path.join(BASE_OUTPUT_DIR, "forest_analysis.txt")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    is_demo = meta_recent.get("is_demo_data", False) or meta_recent.get("processing_mode") == "DEMO"
    proc_mode = "DEMO" if is_demo else "REAL"
    data_src = meta_recent.get("data_source", "DEMO_SYNTHETIC" if is_demo else "COPERNICUS_SENTINEL_2_L2A")
    provenance = meta_recent.get("provenance", "Copernicus Sentinel-2 Level-2A via Google Earth Engine")

    lines = []
    if is_demo:
        lines.extend([
            "================================================================================",
            "*** DEMO DATA NOTICE: THIS REPORT WAS GENERATED USING SYNTHETIC SIMULATION ***  ",
            "*** NOT ACTUAL SATELLITE OBSERVATIONS. DO NOT USE FOR FIELD INVESTIGATION. ***  ",
            "================================================================================"
        ])

    lines.extend([
        "================================================================================",
        "             FORESTWATCH AI - SATELLITE DEFORESTATION REPORT                    ",
        "================================================================================",
        f"Analysis ID:           {analysis_id}",
        f"Generated At:          {now_str}",
        f"Processing Mode:       {proc_mode}",
        f"Data Source:           {data_src}",
        f"Provenance:            {provenance}",
        f"Status:                Analysis Completed Successfully",
        f"Deforestation Risk:    {change_stats['risk_level']}",
        "--------------------------------------------------------------------------------",
        "1. GEOGRAPHIC & SPATIAL EXTENT",
        "--------------------------------------------------------------------------------",
        f"Center Coordinates:    Latitude {meta_recent.get('latitude', 'N/A')} deg, Longitude {meta_recent.get('longitude', 'N/A')} deg",
        f"Spatial Resolution:    {meta_recent.get('scale_meters', 20)} meters / pixel",
        f"Grid Matrix Size:      {meta_recent.get('shape', ['N/A', 'N/A'])[0]} rows x {meta_recent.get('shape', ['N/A', 'N/A'])[1]} columns",
        f"Total Valid Area:      {change_stats['total_area_ha']:.2f} hectares ({change_stats['total_area_km2']:.4f} km2)",
        f"Total Valid Pixels:    {change_stats['total_valid_pixels']:,} pixels",
        f"Total Masked/Invalid:  {change_stats.get('masked_pixels', 0):,} pixels ({100.0 - change_stats.get('valid_data_pct', 100.0):.2f}%)",
        "",
        "--------------------------------------------------------------------------------",
        "2. SATELLITE OBSERVATIONS & DATA QUALITY",
        "--------------------------------------------------------------------------------",
        f"Data Source:           {data_src} ({meta_recent.get('source', 'Google Earth Engine')})",
        f"SCL Quality Mask:      Cloud, shadow, cirrus and invalid reflectance filtered",
        "",
        "Baseline Observation (T1):",
        f"  - Target Query:      {meta_baseline.get('query_start_date', 'N/A')} to {meta_baseline.get('query_end_date', 'N/A')}",
        f"  - Scene Date/Time:   {meta_baseline.get('acquisition_date', 'N/A')}",
        f"  - Spacecraft/Sensor: {meta_baseline.get('spacecraft', 'Sentinel-2')}",
        f"  - Cloud Coverage:    {meta_baseline.get('cloud_percentage', 0.0):.2f}%",
        f"  - Scene Identifier:  {meta_baseline.get('scene_id', 'N/A')}",
        "",
        "Recent Observation (T2):",
        f"  - Target Query:      {meta_recent.get('query_start_date', 'N/A')} to {meta_recent.get('query_end_date', 'N/A')}",
        f"  - Scene Date/Time:   {meta_recent.get('acquisition_date', 'N/A')}",
        f"  - Spacecraft/Sensor: {meta_recent.get('spacecraft', 'Sentinel-2')}",
        f"  - Cloud Coverage:    {meta_recent.get('cloud_percentage', 0.0):.2f}%",
        f"  - Scene Identifier:  {meta_recent.get('scene_id', 'N/A')}",
        "",
        "--------------------------------------------------------------------------------",
        "3. VEGETATION INDEX (NDVI) METRICS",
        "--------------------------------------------------------------------------------",
        f"Baseline NDVI:         Min = {base_stats['min_ndvi']:.3f}, Max = {base_stats['max_ndvi']:.3f}, Mean = {base_stats['mean_ndvi']:.3f} (+/-{base_stats['std_ndvi']:.3f})",
        f"Recent NDVI:           Min = {recent_stats['min_ndvi']:.3f}, Max = {recent_stats['max_ndvi']:.3f}, Mean = {recent_stats['mean_ndvi']:.3f} (+/-{recent_stats['std_ndvi']:.3f})",
        f"Mean NDVI Delta:       {change_stats['mean_delta_ndvi']:+.4f} (Vegetation index difference T2 - T1)",
        "",
        "--------------------------------------------------------------------------------",
        "4. MULTI-TEMPORAL CHANGE & VEGETATION DETECTION",
        "--------------------------------------------------------------------------------",
        f"{'Class Category':<28} | {'Pixels':>10} | {'Area (ha)':>12} | {'Area (km2)':>12} | {'% of AOI':>10}",
        "-" * 80,
        f"{'Potential Vegetation Loss':<28} | {change_stats['deforested']['pixels']:>10,} | {change_stats['deforested']['hectares']:>12.2f} | {change_stats['deforested']['km2']:>12.4f} | {change_stats['deforested']['percentage']:>9.2f}%",
        f"{'Stable Dense Forest':<28} | {change_stats['stable_dense']['pixels']:>10,} | {change_stats['stable_dense']['hectares']:>12.2f} | {change_stats['stable_dense']['km2']:>12.4f} | {change_stats['stable_dense']['percentage']:>9.2f}%",
        f"{'Stable Light Forest':<28} | {change_stats['stable_light']['pixels']:>10,} | {change_stats['stable_light']['hectares']:>12.2f} | {change_stats['stable_light']['km2']:>12.4f} | {change_stats['stable_light']['percentage']:>9.2f}%",
        f"{'Regrowth / Gain':<28} | {change_stats['regrowth']['pixels']:>10,} | {change_stats['regrowth']['hectares']:>12.2f} | {change_stats['regrowth']['km2']:>12.4f} | {change_stats['regrowth']['percentage']:>9.2f}%",
        f"{'Persistent Non-Forest':<28} | {change_stats['non_forest']['pixels']:>10,} | {change_stats['non_forest']['hectares']:>12.2f} | {change_stats['non_forest']['km2']:>12.4f} | {change_stats['non_forest']['percentage']:>9.2f}%",
        "-" * 80,
        f"{'Total Valid Analyzed Area':<28} | {change_stats['total_valid_pixels']:>10,} | {change_stats['total_area_ha']:>12.2f} | {change_stats['total_area_km2']:>12.4f} | {100.00:>9.2f}%",
        "",
        "--------------------------------------------------------------------------------",
        "5. CONSERVATION GUIDANCE & SCIENTIFIC LIMITATIONS",
        "--------------------------------------------------------------------------------",
        f"Alert Level:           {change_stats['risk_level']}",
        f"Potential Canopy Loss: {change_stats['deforested']['hectares']:.2f} hectares ({change_stats['deforested']['percentage']:.2f}% of monitored zone)",
        "",
        "Scientific Limitations:",
        "- NDVI measures canopy greenness and photosynthetic activity; it is an indicator, not legal verification.",
        "- Satellite-detected vegetation decline indicates potential disturbance and requires field verification.",
        "- Ground truthing and patrol validation are required before legal or enforcement actions.",
        "- Cloud shadows and topography can cause localized reflectance artifacts despite SCL masking.",
        "================================================================================",
        "End of Report. ForestWatch AI Remote Sensing Monitoring System."
    ])

    report_text = "\n".join(lines) + "\n"

    with open(report_path, "w") as f:
        f.write(report_text)

    try:
        shutil.copyfile(report_path, latest_path)
    except Exception as e:
        logger.warning(f"Could not copy latest report: {e}")

    return report_path


def export_pdf_report(analysis_id, summary_dict, report_text, chart_path, map_path, pdf_path):
    """
    Generate an executive PDF report using FPDF2 with ForestWatch AI branding.
    """
    try:
        pdf = FPDF(orientation='P', unit='mm', format='A4')
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        is_demo = summary_dict.get("is_demo_data", False) or summary_dict.get("processing_mode") == "DEMO"
        proc_mode = "DEMO (SYNTHETIC SIMULATION)" if is_demo else "REAL SATELLITE (COPERNICUS SENTINEL-2)"

        # Header banner
        pdf.set_fill_color(18, 59, 42)  # #123B2A
        pdf.rect(0, 0, 210, 28, 'F')

        pdf.set_font('helvetica', 'B', 18)
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(10, 6)
        pdf.cell(190, 8, clean_pdf_text("ForestWatch AI - Environmental Intelligence Report"), align='C')

        pdf.set_font('helvetica', '', 10)
        pdf.set_text_color(159, 227, 176)  # Mint #9FE3B0
        pdf.set_xy(10, 15)
        pdf.cell(190, 6, clean_pdf_text("Copernicus Sentinel-2 Surface Reflectance Satellite Analysis"), align='C')

        current_y = 32
        if is_demo:
            pdf.set_fill_color(220, 53, 69)  # Red warning banner
            pdf.rect(0, 28, 210, 8, 'F')
            pdf.set_font('helvetica', 'B', 9)
            pdf.set_text_color(255, 255, 255)
            pdf.set_xy(10, 29)
            pdf.cell(190, 6, clean_pdf_text("*** DEMO MODE: SYNTHETIC DATA FOR EVALUATION ONLY - NOT ACTUAL OBSERVATIONS ***"), align='C')
            current_y = 38

        pdf.set_xy(10, current_y)
        pdf.set_text_color(33, 33, 33)

        # Overview Table
        cs = summary_dict.get("change_stats", {})
        loc = summary_dict.get("location", {})

        pdf.set_font('helvetica', 'B', 12)
        pdf.cell(0, 7, clean_pdf_text(f"Analysis Summary (ID: {analysis_id})"), new_x='LMARGIN', new_y='NEXT')

        pdf.set_font('helvetica', '', 9)
        pdf.cell(95, 6, clean_pdf_text(f"Coordinates: {loc.get('latitude', '')} deg N, {loc.get('longitude', '')} deg E"), border=1)
        pdf.cell(95, 6, clean_pdf_text(f"Status / Risk: {cs.get('risk_level', 'Completed')}"), border=1, new_x='LMARGIN', new_y='NEXT')

        pdf.cell(95, 6, clean_pdf_text(f"Processing Mode: {proc_mode}"), border=1)
        pdf.cell(95, 6, clean_pdf_text(f"Total Valid Area: {cs.get('total_area_ha', 0)} ha ({cs.get('total_area_km2', 0)} km2)"), border=1, new_x='LMARGIN', new_y='NEXT')

        pdf.cell(95, 6, clean_pdf_text(f"Potential Loss: {cs.get('deforested', {}).get('hectares', 0)} ha ({cs.get('deforested', {}).get('percentage', 0)}%)"), border=1)
        pdf.cell(95, 6, clean_pdf_text(f"Mean Delta NDVI: {cs.get('mean_delta_ndvi', 0):+.4f}"), border=1, new_x='LMARGIN', new_y='NEXT')

        pdf.cell(95, 6, clean_pdf_text(f"Stable Dense Forest: {cs.get('stable_dense', {}).get('hectares', 0)} ha ({cs.get('stable_dense', {}).get('percentage', 0)}%)"), border=1)
        pdf.cell(95, 6, clean_pdf_text(f"Masked/Invalid: {cs.get('masked_pixels', 0)} px ({100.0 - cs.get('valid_data_pct', 100.0):.1f}%)"), border=1, new_x='LMARGIN', new_y='NEXT')

        pdf.ln(4)

        # Embed spatial change map
        if os.path.exists(map_path):
            pdf.set_font('helvetica', 'B', 11)
            pdf.cell(0, 6, clean_pdf_text("1. Multi-Temporal Spatial Change Map:"), new_x='LMARGIN', new_y='NEXT')
            pdf.image(map_path, x=15, y=pdf.get_y(), w=180)
            pdf.ln(135)

        # Page 2: Charts and Full Classification Breakdown
        pdf.add_page()
        if os.path.exists(chart_path):
            pdf.set_font('helvetica', 'B', 11)
            pdf.cell(0, 6, clean_pdf_text("2. Forest Cover & Change Statistics:"), new_x='LMARGIN', new_y='NEXT')
            pdf.image(chart_path, x=15, y=pdf.get_y(), w=180)
            pdf.ln(65)

        # Scientific Disclaimer Box
        pdf.set_fill_color(245, 247, 242)
        pdf.set_draw_color(46, 139, 87)
        pdf.rect(10, pdf.get_y(), 190, 26, 'DF')
        pdf.set_xy(12, pdf.get_y() + 2)
        pdf.set_font('helvetica', 'B', 9)
        pdf.set_text_color(18, 59, 42)
        pdf.cell(0, 5, clean_pdf_text("Scientific Methodology & Governance Disclaimer:"), new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('helvetica', '', 8)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(186, 4, clean_pdf_text(
            "This report is generated from Copernicus Sentinel-2 Level-2A surface reflectance data processed via Google Earth Engine. "
            "NDVI thresholds indicate changes in canopy photosynthetic activity and are not legal boundaries. "
            "Satellite-detected vegetation decline indicates potential disturbance and requires field verification."
        ))

        pdf.output(pdf_path)
        logger.info(f"PDF report successfully exported: {pdf_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to generate PDF report: {e}")
        return False


def export_csv_summary(analysis_id, summary_dict, csv_path):
    """Export analysis metrics to clean CSV format"""
    try:
        cs = summary_dict.get("change_stats", {})
        loc = summary_dict.get("location", {})
        rows = [
            ["Metric", "Value", "Unit"],
            ["Analysis_ID", analysis_id, ""],
            ["Processing_Mode", summary_dict.get("processing_mode", "REAL"), ""],
            ["Data_Source", summary_dict.get("data_source", "COPERNICUS_SENTINEL_2_L2A"), ""],
            ["Is_Demo_Data", summary_dict.get("is_demo_data", False), ""],
            ["Latitude", loc.get("latitude", ""), "degrees"],
            ["Longitude", loc.get("longitude", ""), "degrees"],
            ["Total_Area_Hectares", cs.get("total_area_ha", 0), "ha"],
            ["Total_Area_Km2", cs.get("total_area_km2", 0), "km2"],
            ["Total_Valid_Pixels", cs.get("total_valid_pixels", 0), "pixels"],
            ["Total_Masked_Pixels", cs.get("masked_pixels", 0), "pixels"],
            ["Valid_Data_Pct", cs.get("valid_data_pct", 100.0), "%"],
            ["Mean_Delta_NDVI", cs.get("mean_delta_ndvi", 0), "index"],
            ["Risk_Alert_Level", cs.get("risk_level", "N/A"), ""],
            ["Deforested_Pixels", cs.get("deforested", {}).get("pixels", 0), "pixels"],
            ["Deforested_Hectares", cs.get("deforested", {}).get("hectares", 0), "ha"],
            ["Deforested_Percentage", cs.get("deforested", {}).get("percentage", 0), "%"],
            ["Stable_Dense_Hectares", cs.get("stable_dense", {}).get("hectares", 0), "ha"],
            ["Stable_Dense_Percentage", cs.get("stable_dense", {}).get("percentage", 0), "%"],
            ["Stable_Light_Hectares", cs.get("stable_light", {}).get("hectares", 0), "ha"],
            ["Stable_Light_Percentage", cs.get("stable_light", {}).get("percentage", 0), "%"],
            ["Regrowth_Hectares", cs.get("regrowth", {}).get("hectares", 0), "ha"],
            ["Regrowth_Percentage", cs.get("regrowth", {}).get("percentage", 0), "%"]
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        return True
    except Exception as e:
        logger.error(f"Failed to generate CSV: {e}")
        return False


def create_spatial_map(output_dir, analysis_id, ndvi_baseline, ndvi_recent, delta_ndvi, change_map, meta_recent):
    """
    Generate 4-panel spatial satellite map.
    """
    map_filename = f"temporal_comparison_{analysis_id}.png"
    map_path = os.path.join(output_dir, map_filename)
    latest_path = os.path.join(BASE_OUTPUT_DIR, "temporal_comparison.png")

    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    plt.subplots_adjust(wspace=0.25, hspace=0.30)

    # Base NDVI Colormap (RdYlGn with transparent masked pixels)
    cmap_ndvi = plt.colormaps['RdYlGn'].resampled(256).with_extremes(bad='none')

    # 1. Baseline NDVI
    im0 = axes[0, 0].imshow(ndvi_baseline, cmap=cmap_ndvi, vmin=-0.1, vmax=0.8)
    axes[0, 0].set_title("1. Baseline NDVI (T1)", fontsize=13, fontweight='bold')
    axes[0, 0].axis('off')
    cbar0 = fig.colorbar(im0, ax=axes[0, 0], fraction=0.046, pad=0.04)
    cbar0.set_label("NDVI (Green: Dense, Tan/Red: Bare)")

    # 2. Recent NDVI
    im1 = axes[0, 1].imshow(ndvi_recent, cmap=cmap_ndvi, vmin=-0.1, vmax=0.8)
    axes[0, 1].set_title("2. Recent NDVI (T2)", fontsize=13, fontweight='bold')
    axes[0, 1].axis('off')
    cbar1 = fig.colorbar(im1, ax=axes[0, 1], fraction=0.046, pad=0.04)
    cbar1.set_label("NDVI (Green: Dense, Tan/Red: Bare)")

    # 3. Delta NDVI (Change): Red = Loss (negative), Blue = Gain (positive), transparent masked
    cmap_delta = plt.colormaps['coolwarm_r'].resampled(256).with_extremes(bad='none')
    im2 = axes[1, 0].imshow(delta_ndvi, cmap=cmap_delta, vmin=-0.4, vmax=0.4)
    axes[1, 0].set_title("3. Vegetation Change (ΔNDVI = T2 - T1)", fontsize=13, fontweight='bold')
    axes[1, 0].axis('off')
    cbar2 = fig.colorbar(im2, ax=axes[1, 0], fraction=0.046, pad=0.04)
    cbar2.set_label("ΔNDVI (Red: Loss, Blue: Gain)")

    # 4. Categorized Change Map (mask 255 invalid/cloud pixels - transparent, NOT blue!)
    masked_change = np.ma.masked_where(change_map == 255, change_map)
    cmap_change = ListedColormap(['#d3d3d3', '#90ee90', '#1b5e20', '#d50000', '#00b0ff']).with_extremes(bad='none', over='none', under='none')
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5], cmap_change.N)
    im3 = axes[1, 1].imshow(masked_change, cmap=cmap_change, norm=norm)
    axes[1, 1].set_title("4. Multi-Temporal Canopy Disturbance Detection", fontsize=13, fontweight='bold')
    axes[1, 1].axis('off')

    cbar3 = fig.colorbar(im3, ax=axes[1, 1], ticks=[0, 1, 2, 3, 4], fraction=0.046, pad=0.04)
    cbar3.ax.set_yticklabels(['Non-Forest', 'Light Forest', 'Dense Forest', 'Potential Loss', 'Regrowth'])

    is_demo = meta_recent.get("is_demo_data", False) or meta_recent.get("processing_mode") == "DEMO"
    title_prefix = "[DEMO DATA - SIMULATED OBSERVATIONS] " if is_demo else ""
    title_color = "#b71c1c" if is_demo else "#1b5e20"

    fig.suptitle(
        f"{title_prefix}ForestWatch AI — Sentinel-2 Forest Analysis ({meta_recent.get('latitude', '')} deg, {meta_recent.get('longitude', '')} deg)\n"
        f"Resolution: {meta_recent.get('scale_meters', 20)}m | SCL Cloud Masked | Source: {meta_recent.get('data_source', 'COPERNICUS_SENTINEL_2_L2A')} | ID: {analysis_id}",
        fontsize=13, fontweight='bold', color=title_color
    )

    logger.info(
        f"[MAP DIAGNOSTIC] Spatial Map Rendered for Analysis {analysis_id}: "
        f"Baseline NDVI range: [{np.nanmin(ndvi_baseline):.3f}, {np.nanmax(ndvi_baseline):.3f}], "
        f"Recent NDVI range: [{np.nanmin(ndvi_recent):.3f}, {np.nanmax(ndvi_recent):.3f}], "
        f"ΔNDVI range: [{np.nanmin(delta_ndvi):.3f}, {np.nanmax(delta_ndvi):.3f}], "
        f"Transparent masked pixels: {int(np.sum(change_map == 255))}"
    )

    plt.savefig(map_path, dpi=200, bbox_inches='tight')
    plt.close(fig)

    try:
        shutil.copyfile(map_path, latest_path)
    except Exception as e:
        logger.warning(f"Could not copy latest spatial map: {e}")

    return map_path


def create_statistical_charts(output_dir, analysis_id, base_stats, recent_stats, change_stats, ndvi_baseline, ndvi_recent):
    """
    Generate statistical charts.
    """
    chart_filename = f"forest_classification_{analysis_id}.png"
    chart_path = os.path.join(output_dir, chart_filename)
    latest_path = os.path.join(BASE_OUTPUT_DIR, "forest_classification.png")

    fig = plt.figure(figsize=(15, 5))

    # 1. Grouped Bar Chart
    ax1 = fig.add_subplot(1, 3, 1)
    labels = ['Dense Forest', 'Light Forest', 'Non-Forest']
    base_vals = [base_stats['dense_pct'], base_stats['light_pct'], base_stats['non_forest_pct']]
    recent_vals = [recent_stats['dense_pct'], recent_stats['light_pct'], recent_stats['non_forest_pct']]

    x = np.arange(len(labels))
    width = 0.35

    ax1.bar(x - width/2, base_vals, width, label='Baseline (T1)', color='#2e7d32', alpha=0.85)
    ax1.bar(x + width/2, recent_vals, width, label='Recent (T2)', color='#f57c00', alpha=0.85)
    ax1.set_ylabel('Percentage of Analyzed Area (%)', fontweight='bold')
    ax1.set_title('Forest Cover: Baseline vs Recent', fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=15)
    ax1.legend()
    ax1.grid(axis='y', linestyle='--', alpha=0.5)

    # 2. Multi-Temporal Change Pie
    ax2 = fig.add_subplot(1, 3, 2)
    change_labels = ['Stable Dense', 'Stable Light', 'Deforested', 'Regrowth', 'Non-Forest']
    change_sizes = [
        change_stats['stable_dense']['percentage'],
        change_stats['stable_light']['percentage'],
        change_stats['deforested']['percentage'],
        change_stats['regrowth']['percentage'],
        change_stats['non_forest']['percentage']
    ]
    colors = ['#1b5e20', '#90ee90', '#d50000', '#00b0ff', '#bdbdbd']
    explode = (0, 0, 0.15 if change_stats['deforested']['percentage'] > 0 else 0, 0, 0)

    filtered_data = [(l, s, c, e) for l, s, c, e in zip(change_labels, change_sizes, colors, explode) if s > 0.05]
    if filtered_data:
        f_labels, f_sizes, f_colors, f_explode = zip(*filtered_data)
        ax2.pie(f_sizes, explode=f_explode, labels=f_labels, colors=f_colors,
                autopct='%1.1f%%', shadow=True, startangle=140, pctdistance=0.75)
    ax2.set_title('Multi-Temporal Land Cover Change', fontweight='bold')

    # 3. NDVI Histograms
    ax3 = fig.add_subplot(1, 3, 3)
    valid_base = ndvi_baseline[~np.isnan(ndvi_baseline)].ravel()
    valid_rec = ndvi_recent[~np.isnan(ndvi_recent)].ravel()

    ax3.hist(valid_base, bins=40, range=(-0.2, 0.9), alpha=0.55, color='green', label=f"Baseline (u={base_stats['mean_ndvi']:.2f})")
    ax3.hist(valid_rec, bins=40, range=(-0.2, 0.9), alpha=0.55, color='orange', label=f"Recent (u={recent_stats['mean_ndvi']:.2f})")
    ax3.axvline(NDVI_LIGHT_FOREST_MAX, color='darkgreen', linestyle='--', label=f'Forest Threshold ({NDVI_LIGHT_FOREST_MAX})')
    ax3.set_xlabel('NDVI Value', fontweight='bold')
    ax3.set_ylabel('Pixel Frequency', fontweight='bold')
    ax3.set_title('NDVI Distribution Shift', fontweight='bold')
    ax3.legend(fontsize=8)
    ax3.grid(axis='y', linestyle='--', alpha=0.5)

    plt.tight_layout()
    plt.savefig(chart_path, dpi=200, bbox_inches='tight')
    plt.close(fig)

    try:
        shutil.copyfile(chart_path, latest_path)
    except Exception as e:
        logger.warning(f"Could not copy latest chart: {e}")

    return chart_path


def generate_historical_trends_chart(output_dir, analysis_id, hist_result):
    """
    Generate multi-year historical trend charts:
    1. Annual Mean & Median NDVI curves with standard deviation band.
    2. Stacked bar chart of Dense vs Light vs Non-forest percentage.
    3. Year-on-year Delta NDVI bar chart.
    """
    chart_filename = f"historical_trends_{analysis_id}.png"
    chart_path = os.path.join(output_dir, chart_filename)

    years_data = hist_result.get("years", [])
    if not years_data:
        return None

    years = [y["year"] for y in years_data]
    mean_ndvi = [y["mean_ndvi"] for y in years_data]
    median_ndvi = [y["median_ndvi"] for y in years_data]
    std_ndvi = [y["std_ndvi"] for y in years_data]
    dense_pct = [y["dense_pct"] for y in years_data]
    light_pct = [y["light_pct"] for y in years_data]
    non_pct = [y["non_forest_pct"] for y in years_data]
    yoy_changes = [y.get("yoy_change", 0.0) for y in years_data]

    fig, axes = plt.subplots(3, 1, figsize=(12, 11), sharex=True)
    plt.subplots_adjust(hspace=0.25)

    # Subplot 1: Annual NDVI Trajectory
    axes[0].plot(years, mean_ndvi, marker='o', linewidth=2.5, color='#1b5e20', label='Annual Mean NDVI')
    axes[0].plot(years, median_ndvi, marker='s', linestyle='--', color='#2e7d32', label='Annual Median NDVI')
    # Fill +/- 1 std dev
    lower_bound = np.array(mean_ndvi) - np.array(std_ndvi)
    upper_bound = np.array(mean_ndvi) + np.array(std_ndvi)
    axes[0].fill_between(years, lower_bound, upper_bound, color='#a5d6a7', alpha=0.35, label='1 Std Deviation Band')
    axes[0].axhline(0.50, color='darkgreen', linestyle=':', label='Dense Forest Threshold (0.50)')
    axes[0].set_ylabel('NDVI Index', fontweight='bold')
    axes[0].set_title(f"Historical Vegetation Index Trajectory ({years[0]} - {years[-1]})", fontsize=13, fontweight='bold')
    axes[0].grid(True, linestyle='--', alpha=0.5)
    axes[0].legend(loc='lower left')

    # Subplot 2: Forest Composition Stacked Bar
    x = np.arange(len(years))
    width = 0.55
    axes[1].bar(years, dense_pct, width, label='Dense Forest (%)', color='#1b5e20', alpha=0.88)
    axes[1].bar(years, light_pct, width, bottom=dense_pct, label='Light Forest (%)', color='#81c784', alpha=0.88)
    bottom_two = np.array(dense_pct) + np.array(light_pct)
    axes[1].bar(years, non_pct, width, bottom=bottom_two, label='Non-Forest (%)', color='#b0bec5', alpha=0.88)
    axes[1].set_ylabel('Area Composition (%)', fontweight='bold')
    axes[1].set_title('Annual Forest Cover Composition Shift', fontsize=12, fontweight='bold')
    axes[1].set_ylim(0, 105)
    axes[1].grid(axis='y', linestyle='--', alpha=0.5)
    axes[1].legend(loc='lower left')

    # Subplot 3: Year-on-Year Delta NDVI
    bar_colors = ['#d32f2f' if d < -0.02 else '#2e7d32' if d > 0.02 else '#78909c' for d in yoy_changes]
    axes[2].bar(years, yoy_changes, width=0.5, color=bar_colors, alpha=0.9)
    axes[2].axhline(0, color='black', linewidth=0.8)
    axes[2].set_xlabel('Observation Year', fontweight='bold')
    axes[2].set_ylabel('YoY Delta NDVI', fontweight='bold')
    axes[2].set_title('Year-on-Year Vegetation Change (Red = Canopy Decline, Green = Recovery)', fontsize=12, fontweight='bold')
    axes[2].set_xticks(years)
    axes[2].grid(True, linestyle='--', alpha=0.5)

    fig.suptitle(f"ForestWatch AI — Multi-Year Historical Satellite Trends\nLocation: ({hist_result['location']['latitude']} deg, {hist_result['location']['longitude']} deg)", fontsize=14, fontweight='bold')

    plt.savefig(chart_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    return chart_path


def send_email_report(report_path, chart_path, map_path, change_stats, cancel_event=None):
    """
    Send email report with attached text report and generated charts.
    """
    if cancel_event and cancel_event.is_set():
        return False, "Cancelled"

    cfg = get_email_config()
    if not cfg["sender"] or not cfg["password"] or not cfg["recipient"]:
        msg = "Email notification skipped: EMAIL_SENDER, EMAIL_PASSWORD, or EMAIL_RECIPIENT not set in environment."
        logger.info(msg)
        return False, msg

    try:
        msg = MIMEMultipart()
        msg['From'] = cfg['sender']
        msg['To'] = cfg['recipient']
        msg['Subject'] = f"{cfg['subject']} - Alert Level: {change_stats.get('risk_level', 'Report')}"

        body = f"""Hello,

Your ForestWatch AI satellite forest cover analysis has completed.

Summary Findings:
-----------------
* Deforestation Risk Level: {change_stats.get('risk_level', 'N/A')}
* Detected Forest Loss:     {change_stats['deforested']['hectares']:.2f} ha ({change_stats['deforested']['percentage']:.2f}% of AOI)
* Stable Dense Forest:      {change_stats['stable_dense']['hectares']:.2f} ha ({change_stats['stable_dense']['percentage']:.2f}%)
* Mean NDVI Change:         {change_stats['mean_delta_ndvi']:+.4f}

Please find the comprehensive report and satellite maps attached.

Regards,
ForestWatch AI Automated Geospatial Pipeline
"""
        msg.attach(MIMEText(body, 'plain'))

        for path in [report_path, chart_path, map_path]:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(path))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
                    msg.attach(part)

        try:
            server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=12)
            server.login(cfg['sender'], cfg['password'])
            server.send_message(msg)
            server.quit()
            return True, "Email sent successfully via SSL"
        except Exception:
            server = smtplib.SMTP(cfg['host'], 587, timeout=12)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(cfg['sender'], cfg['password'])
            server.send_message(msg)
            server.quit()
            return True, "Email sent successfully via STARTTLS"

    except Exception as e:
        return False, f"Failed to send email: {str(e)}"


def run_analysis_pipeline(analysis_id, params=None, cancel_event=None, progress_callback=None):
    """
    Main integrated analysis pipeline for baseline-vs-recent comparison.
    """
    def log(msg):
        logger.info(f"[{analysis_id}] {msg}")
        if progress_callback:
            progress_callback(msg)

    params = params or {}
    lat = float(params.get("latitude", 15.0))
    lon = float(params.get("longitude", 75.0))
    baseline_start = str(params.get("baseline_start", "2022-01-01"))
    baseline_end = str(params.get("baseline_end", "2022-05-31"))
    recent_start = str(params.get("recent_start", "2023-01-01"))
    recent_end = str(params.get("recent_end", "2023-05-31"))
    max_cloud_pct = float(params.get("max_cloud_pct", 25))
    radius_meters = float(params.get("radius_meters", 2000))
    scale = int(params.get("scale", 20))
    demo_mode = bool(params.get("demo_mode", False))

    output_dir = os.path.join(BASE_OUTPUT_DIR, analysis_id)
    os.makedirs(output_dir, exist_ok=True)

    log(f"Starting ForestWatch AI analysis {analysis_id} at ({lat}, {lon}) [demo_mode={demo_mode}]...")

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Analysis cancelled by user before data loading.")

    log(f"Retrieving Sentinel-2 B04 & B08 Surface Reflectance with SCL cloud masking...")
    (b4_base, b8_base, meta_base), (b4_recent, b8_recent, meta_recent) = gee_data_loader.fetch_bitemporal_sentinel2(
        lat=lat, lon=lon,
        baseline_start=baseline_start, baseline_end=baseline_end,
        recent_start=recent_start, recent_end=recent_end,
        radius_meters=radius_meters, scale=scale,
        max_cloud_pct=max_cloud_pct, demo_mode=demo_mode, cancel_event=cancel_event
    )

    log(f"Baseline Scene: {meta_base.get('acquisition_date', 'N/A')}, Clouds: {meta_base.get('cloud_percentage', 0)}%")
    log(f"Recent Scene: {meta_recent.get('acquisition_date', 'N/A')}, Clouds: {meta_recent.get('cloud_percentage', 0)}%")

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Analysis cancelled by user after band loading.")

    log("Calculating NDVI across both observation periods...")
    ndvi_baseline = calculate_ndvi(b4_base, b8_base)
    ndvi_recent = calculate_ndvi(b4_recent, b8_recent)

    log("Classifying single-epoch canopy distributions using verified NDVI thresholds...")
    class_base, base_stats = classify_single_epoch(ndvi_baseline)
    class_recent, recent_stats = classify_single_epoch(ndvi_recent)

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Analysis cancelled by user after single-epoch classification.")

    log("Performing multi-temporal change detection (ΔNDVI)...")
    change_map, delta_ndvi, change_stats = detect_deforestation(
        ndvi_baseline, ndvi_recent, meta_base, meta_recent
    )
    log(f"Canopy Loss Detected: {change_stats['deforested']['hectares']:.2f} ha ({change_stats['deforested']['percentage']}%)")
    log(f"Risk Assessment: {change_stats['risk_level']}")

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Analysis cancelled by user before report generation.")

    log("Generating comprehensive text report...")
    report_path = generate_comprehensive_report(
        output_dir, analysis_id, meta_base, meta_recent,
        base_stats, recent_stats, change_stats
    )

    log("Rendering 4-panel spatial change map and statistical charts...")
    map_path = create_spatial_map(
        output_dir, analysis_id, ndvi_baseline, ndvi_recent, delta_ndvi, change_map, meta_recent
    )
    chart_path = create_statistical_charts(
        output_dir, analysis_id, base_stats, recent_stats, change_stats, ndvi_baseline, ndvi_recent
    )

    is_demo = bool(meta_recent.get("is_demo_data", False) or meta_base.get("is_demo_data", False))
    proc_mode = "DEMO" if is_demo else "REAL"
    data_src = meta_recent.get("data_source", "DEMO_SYNTHETIC" if is_demo else "COPERNICUS_SENTINEL_2_L2A")
    provenance = meta_recent.get("provenance", "DEMO DATA: Synthetic simulation" if is_demo else "Copernicus Sentinel-2 Level-2A via Google Earth Engine")

    # Machine-readable summary
    summary_data = {
        "analysis_id": analysis_id,
        "type": "bitemporal",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "COMPLETED",
        "processing_mode": proc_mode,
        "data_source": data_src,
        "is_demo_data": is_demo,
        "provenance": provenance,
        "location": {"latitude": lat, "longitude": lon},
        "requested_windows": {
            "baseline": [baseline_start, baseline_end],
            "recent": [recent_start, recent_end]
        },
        "analysis_geometry": {
            "type": "Circle",
            "center": [lat, lon],
            "radius_meters": radius_meters,
            "scale_meters": scale
        },
        "masking_method": "SCL Scene Classification & Reflectance Range Filtering",
        "baseline_meta": meta_base,
        "recent_meta": meta_recent,
        "base_stats": base_stats,
        "recent_stats": recent_stats,
        "change_stats": change_stats,
        "report_path": os.path.relpath(report_path, BASE_OUTPUT_DIR),
        "chart_path": os.path.relpath(chart_path, BASE_OUTPUT_DIR),
        "map_path": os.path.relpath(map_path, BASE_OUTPUT_DIR)
    }

    summary_file = os.path.join(output_dir, f"summary_{analysis_id}.json")
    with open(summary_file, "w") as f:
        json.dump(summary_data, f, indent=2)

    # Generate PDF Report and CSV Export
    log("Compiling downloadable PDF and CSV exports...")
    pdf_path = os.path.join(output_dir, f"forest_report_{analysis_id}.pdf")
    export_pdf_report(analysis_id, summary_data, "", chart_path, map_path, pdf_path)

    csv_path = os.path.join(output_dir, f"forest_data_{analysis_id}.csv")
    export_csv_summary(analysis_id, summary_data, csv_path)

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Analysis cancelled by user before email dispatch.")

    log("Checking email notification settings...")
    email_success, email_msg = send_email_report(
        report_path, chart_path, map_path, change_stats, cancel_event=cancel_event
    )
    if email_success:
        log("✅ Email report dispatched successfully!")
    else:
        log(f"ℹ️ {email_msg}")

    log("✅ ForestWatch AI analysis completed successfully!")

    return {
        "analysis_id": analysis_id,
        "report_path": report_path,
        "chart_path": chart_path,
        "map_path": map_path,
        "pdf_path": pdf_path,
        "csv_path": csv_path,
        "summary": summary_data,
        "email_sent": email_success,
        "email_status": email_msg
    }


def run_historical_pipeline(analysis_id, params=None, cancel_event=None, progress_callback=None):
    """
    Run multi-year historical analysis pipeline (e.g. 2018 to 2024).
    """
    def log(msg):
        logger.info(f"[{analysis_id}] {msg}")
        if progress_callback:
            progress_callback(msg)

    params = params or {}
    lat = float(params.get("latitude", 15.0))
    lon = float(params.get("longitude", 75.0))
    start_year = int(params.get("start_year", 2019))
    end_year = int(params.get("end_year", 2024))
    radius_meters = float(params.get("radius_meters", 1500))
    scale = int(params.get("scale", 30))
    demo_mode = bool(params.get("demo_mode", False))

    output_dir = os.path.join(BASE_OUTPUT_DIR, analysis_id)
    os.makedirs(output_dir, exist_ok=True)

    log(f"Starting Multi-Year Historical Analysis {analysis_id} for ({lat}, {lon}) across {start_year}-{end_year} [demo_mode={demo_mode}]...")

    hist_result = gee_data_loader.fetch_multiyear_historical_sentinel2(
        lat=lat, lon=lon,
        start_year=start_year, end_year=end_year,
        radius_meters=radius_meters, scale=scale,
        demo_mode=demo_mode,
        cancel_event=cancel_event, progress_callback=log
    )

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Historical analysis cancelled by user.")

    log("Generating historical trend visualization curves...")
    chart_path = generate_historical_trends_chart(output_dir, analysis_id, hist_result)

    # Save historical text report
    report_filename = f"historical_analysis_{analysis_id}.txt"
    report_path = os.path.join(output_dir, report_filename)

    is_demo = bool(hist_result.get("is_demo_data", False))
    proc_mode = "DEMO" if is_demo else "REAL"
    data_src = "DEMO_SYNTHETIC" if is_demo else "COPERNICUS_SENTINEL_2_L2A"

    lines = []
    if is_demo:
        lines.extend([
            "================================================================================",
            "*** DEMO DATA NOTICE: SYNTHETIC HISTORICAL SIMULATION (NOT ACTUAL SATELLITE) ***",
            "================================================================================"
        ])

    lines.extend([
        "================================================================================",
        "          FORESTWATCH AI - MULTI-YEAR HISTORICAL SATELLITE REPORT               ",
        "================================================================================",
        f"Analysis ID:           {analysis_id}",
        f"Generated At:          {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Target Coordinates:    Latitude {lat} deg, Longitude {lon} deg",
        f"Processing Mode:       {proc_mode}",
        f"Data Source:           {data_src}",
        f"Historical Period:     {start_year} to {end_year} ({len(hist_result.get('years', []))} Years)",
        "--------------------------------------------------------------------------------",
        "ANNUAL NDVI & FOREST COMPOSITION TIME-SERIES",
        "--------------------------------------------------------------------------------",
        f"{'Year':<6} | {'Mean NDVI':>10} | {'Median':>8} | {'Dense %':>9} | {'Light %':>9} | {'YoY Change':>11} | {'Quality'}",
        "-" * 80
    ])

    for y in hist_result.get("years", []):
        lines.append(
            f"{y['year']:<6} | {y['mean_ndvi']:>10.3f} | {y['median_ndvi']:>8.3f} | {y['dense_pct']:>8.1f}% | {y['light_pct']:>8.1f}% | {y.get('yoy_change', 0.0):>+10.3f} | {y.get('trend_indicator', 'N/A')}"
        )

    lines.extend([
        "-" * 80,
        "Methodology: Sentinel-2 Harmonized Level-2A surface reflectance composites with SCL cloud filtering.",
        "================================================================================"
    ])

    report_text = "\n".join(lines) + "\n"
    with open(report_path, "w") as f:
        f.write(report_text)

    # Historical summary JSON
    summary_data = {
        "analysis_id": analysis_id,
        "type": "historical",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "COMPLETED",
        "processing_mode": proc_mode,
        "data_source": data_src,
        "is_demo_data": is_demo,
        "location": {"latitude": lat, "longitude": lon},
        "period": f"{start_year} - {end_year}",
        "historical_data": hist_result,
        "chart_path": os.path.relpath(chart_path, BASE_OUTPUT_DIR) if chart_path else None,
        "report_path": os.path.relpath(report_path, BASE_OUTPUT_DIR)
    }

    summary_file = os.path.join(output_dir, f"summary_{analysis_id}.json")
    with open(summary_file, "w") as f:
        json.dump(summary_data, f, indent=2)

    log("✅ Multi-Year Historical Analysis completed successfully!")

    return {
        "analysis_id": analysis_id,
        "report_path": report_path,
        "chart_path": chart_path,
        "summary": summary_data
    }


# Backwards compatibility legacy functions
def load_bands():
    (b4, b8, _), _ = gee_data_loader.fetch_bitemporal_sentinel2(15.0, 75.0, "2023-01-01", "2023-05-31", "2024-01-01", "2024-05-31")
    return b4, b8

def classify_forest(ndvi):
    _, stats = classify_single_epoch(ndvi)
    return {'dense_forest': stats['dense_pixels'], 'light_forest': stats['light_pixels'], 'deforested': stats['non_forest_pixels'], 'total': stats['total_pixels']}

def generate_report(classification):
    report_path = os.path.join(BASE_OUTPUT_DIR, "forest_analysis.txt")
    with open(report_path, 'w') as f:
        f.write("ForestWatch AI Analysis Report\n")
    return report_path

def create_visualization(classification):
    chart_path = os.path.join(BASE_OUTPUT_DIR, "forest_classification.png")
    return chart_path

def send_email(report_path, chart_path):
    pass
