# ForestWatch AI — Satellite Forest & Deforestation Intelligence

**ForestWatch AI** is a professional geospatial intelligence platform for environmental agencies, forestry departments, conservation teams, and researchers. It provides multi-temporal forest canopy monitoring, automated SCL-masked cloud filtering, scientific NDVI classification, multi-year historical trend analysis, and decision-ready reporting powered by Copernicus Sentinel-2 Level-2A surface reflectance data and Google Earth Engine.

---

## 🌟 Key Platform Capabilities

1. **Forest Location Explorer**:
   - Interactive Leaflet map with satellite imagery and street tile layers.
   - Search for national parks, wildlife sanctuaries, biosphere reserves, and cities via geocoding.
   - Draggable marker and circular Monitoring Area (AOI) with real-time hectare area calculations.
   - Persistent library of saved forest monitoring zones (`saved_locations.json`).

2. **Real Copernicus Sentinel-2 Satellite Processing**:
   - Live query of `COPERNICUS/S2_SR_HARMONIZED` Surface Reflectance.
   - Real B04 (Red, 665 nm) and B08 (NIR, 842 nm) spectral bands at 20m spatial resolution.
   - Pixel-level **Scene Classification Layer (SCL)** filtering to mask cloud shadows (SCL 3), clouds (SCL 8, 9), cirrus (SCL 10), and snow (SCL 11).

3. **Data-Driven Scientific NDVI & Change Detection**:
   $$\text{NDVI} = \frac{\text{B08} - \text{B04}}{\text{B08} + \text{B04}}$$
   - Validated classification thresholds:
     - **Dense Forest Canopy**: $\text{NDVI} \ge 0.50$
     - **Light / Sparse Forest**: $0.20 \le \text{NDVI} < 0.50$
     - **Non-Forest / Barren / Water**: $\text{NDVI} < 0.20$
   - Bi-temporal change detection ($\Delta\text{NDVI} = \text{NDVI}_{T2} - \text{NDVI}_{T1}$):
     - **Deforested (Canopy Loss)**: Baseline forest ($\text{NDVI} \ge 0.40$) suffering significant loss ($\Delta\text{NDVI} \le -0.15$).
     - **Stable Dense Forest**: $\text{NDVI} \ge 0.50$ in both epochs.
     - **Regrowth / Gain**: $\text{NDVI}_{T1} < 0.30$ transitioning to $\text{NDVI}_{T2} \ge 0.45$.

4. **Multi-Year Historical Trend Analysis (2018–2024)**:
   - Annual seasonal median composites with SCL cloud & shadow filtering.
   - Historical time-series curves: Annual Mean & Median NDVI, standard deviation envelopes, stacked forest composition bars, and Year-on-Year delta change bars.
   - Smart local caching of completed years to conserve Google Earth Engine processing quotas and execution time.

5. **Decision-Ready Reports & Multi-Format Exports**:
   - **Executive PDF Report**: Built with `fpdf2`, featuring official ForestWatch AI branding, summary tables, scientific methodology notes, and embedded 4-panel satellite maps and charts.
   - **CSV Metrics Export**: Raw quantitative data (hectares, pixel counts, percentages, NDVI delta) for GIS software integration (QGIS, ArcGIS).
   - **Comprehensive Text Report**: Detailed statistics, coordinates, and actionable conservation guidance.

6. **Enterprise Architecture & Security**:
   - Cooperative cancellation tokens (`threading.Event()`) with instant `/stop-analysis`.
   - Results isolated in dedicated run directories (`static/sentinel_output/<id>/`).
   - Secure environment variable credential management (`.env`) with `.gitignore` protection.

---

## 🚀 Quick Start Guide

### 1. Requirements
- Python 3.9+
- Google Earth Engine authenticated account (`earthengine-api`)

### 2. Installation
```bash
git clone https://github.com/Vaishnaviwalikar/ForestWatch-AI
cd Sentinel_2-Project
pip install -r requirements.txt
```

### 3. Environment Setup
Copy the template configuration:
```bash
cp .env.example .env
```
Edit `.env` with your Google Cloud Project ID and optional SMTP email credentials:
```env
GEE_PROJECT=boxwood-well-512915-r3

# Optional: Email Notifications (Use a 16-character Gmail App Password)
EMAIL_SENDER=
EMAIL_PASSWORD=
EMAIL_RECIPIENT=
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
```

### 4. Launch ForestWatch AI Web Dashboard
```bash
python3 app.py
```
Open **`http://127.0.0.1:5000`** in your browser.

---

## 🖥️ Application Modules

- **Dashboard / New Analysis**: Configure coordinates, Baseline ($T_1$) and Recent ($T_2$) observation windows, and run analysis.
- **Location Explorer**: Interactive Leaflet map with geocoding search for global forests and parks. Click on the map to define custom monitoring circles and save them to the library.
- **Historical Trends**: Select start and end years (e.g. 2019 to 2024) to evaluate historical vegetation trajectories.
- **Reports & History**: Inspect past analysis records and download PDF and CSV files directly.

---

## 🧪 Running the Test Suite
ForestWatch AI includes unit tests for NDVI math, zero-denominator safeguards, classification thresholds, deforestation delta calculations, and area metrics:
```bash
python3 test_scientific_calculations.py
```

---

## 📋 Scientific Disclaimer & Governance
ForestWatch AI calculates vegetation indices based on satellite surface reflectance. NDVI measures canopy photosynthetic vitality and serves as an environmental indicator; it does not constitute legal boundary determination or confirmed criminal deforestation without field verification and ground-truthing by authorized forestry officers.
