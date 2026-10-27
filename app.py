from flask import Flask, render_template, jsonify, request, send_from_directory, send_file
import os
import sys
import json
import logging
import threading
import uuid
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()])
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.path.join(BASE_DIR, "static", "sentinel_output")
LOCATIONS_FILE = os.path.join(BASE_DIR, "saved_locations.json")
os.makedirs(OUTPUT_ROOT, exist_ok=True)

# Thread-safe in-memory registry of analyses
jobs_lock = threading.Lock()
jobs = {}
latest_analysis_id = None


def get_job(analysis_id=None):
    """Retrieve job state by ID, or the most recent job if ID is None"""
    with jobs_lock:
        if analysis_id and analysis_id in jobs:
            return jobs[analysis_id]
        if latest_analysis_id and latest_analysis_id in jobs:
            return jobs[latest_analysis_id]
        return None


def execute_bitemporal_worker(analysis_id, params, cancel_event):
    """Background worker executing the bitemporal Sentinel-2 analysis pipeline"""
    import Anni_code

    job = jobs[analysis_id]

    def log_progress(msg):
        with jobs_lock:
            job["messages"].append(msg)

    try:
        job["status"] = "running"
        job["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_progress("Initializing Sentinel-2 processing pipeline...")

        result = Anni_code.run_analysis_pipeline(
            analysis_id=analysis_id,
            params=params,
            cancel_event=cancel_event,
            progress_callback=log_progress
        )

        with jobs_lock:
            job["status"] = "completed"
            job["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            job["report_path"] = result["report_path"]
            job["chart_path"] = result["chart_path"]
            job["map_path"] = result["map_path"]
            job["pdf_path"] = result.get("pdf_path")
            job["csv_path"] = result.get("csv_path")
            job["summary"] = result["summary"]
            job["email_sent"] = result["email_sent"]
            job["email_status"] = result["email_status"]
            job["rel_report_path"] = f"sentinel_output/{analysis_id}/forest_analysis_{analysis_id}.txt"
            job["rel_chart_path"] = f"sentinel_output/{analysis_id}/forest_classification_{analysis_id}.png"
            job["rel_map_path"] = f"sentinel_output/{analysis_id}/temporal_comparison_{analysis_id}.png"

    except InterruptedError:
        with jobs_lock:
            job["status"] = "cancelled"
            job["messages"].append("⏹ Analysis was cancelled by user.")
        logger.info(f"Analysis {analysis_id} successfully cancelled.")

    except Exception as e:
        with jobs_lock:
            job["status"] = "error"
            job["messages"].append(f"❌ Error: {str(e)}")
        logger.error(f"Error in analysis {analysis_id}: {str(e)}", exc_info=True)


def execute_historical_worker(analysis_id, params, cancel_event):
    """Background worker executing the multi-year historical analysis pipeline"""
    import Anni_code

    job = jobs[analysis_id]

    def log_progress(msg):
        with jobs_lock:
            job["messages"].append(msg)

    try:
        job["status"] = "running"
        job["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_progress("Initializing multi-year historical satellite analysis...")

        result = Anni_code.run_historical_pipeline(
            analysis_id=analysis_id,
            params=params,
            cancel_event=cancel_event,
            progress_callback=log_progress
        )

        with jobs_lock:
            job["status"] = "completed"
            job["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            job["report_path"] = result["report_path"]
            job["chart_path"] = result["chart_path"]
            job["summary"] = result["summary"]
            job["rel_report_path"] = f"sentinel_output/{analysis_id}/historical_analysis_{analysis_id}.txt"
            job["rel_chart_path"] = f"sentinel_output/{analysis_id}/historical_trends_{analysis_id}.png"

    except InterruptedError:
        with jobs_lock:
            job["status"] = "cancelled"
            job["messages"].append("⏹ Historical analysis was cancelled by user.")
        logger.info(f"Historical analysis {analysis_id} cancelled.")

    except Exception as e:
        with jobs_lock:
            job["status"] = "error"
            job["messages"].append(f"❌ Error: {str(e)}")
        logger.error(f"Error in historical analysis {analysis_id}: {str(e)}", exc_info=True)


@app.route('/')
def index():
    """Render the ForestWatch AI dashboard"""
    return render_template('index.html')


@app.route('/run-analysis', methods=['POST'])
def start_analysis():
    """Start a bitemporal analysis job"""
    global latest_analysis_id

    payload = request.get_json(silent=True) or request.form or {}
    
    timestamp_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    analysis_id = f"analysis_{timestamp_tag}_{rand_suffix}"

    params = {
        "latitude": float(payload.get("latitude", 15.0)),
        "longitude": float(payload.get("longitude", 75.0)),
        "baseline_start": payload.get("baseline_start", "2022-01-01"),
        "baseline_end": payload.get("baseline_end", "2022-05-31"),
        "recent_start": payload.get("recent_start", "2023-01-01"),
        "recent_end": payload.get("recent_end", "2023-05-31"),
        "max_cloud_pct": float(payload.get("max_cloud_pct", 25)),
        "radius_meters": float(payload.get("radius_meters", 2000)),
        "scale": int(payload.get("scale", 20))
    }

    cancel_event = threading.Event()

    job_record = {
        "id": analysis_id,
        "type": "bitemporal",
        "status": "starting",
        "params": params,
        "messages": [f"Analysis {analysis_id} queued..."],
        "cancel_event": cancel_event,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": None,
        "report_path": None,
        "chart_path": None,
        "map_path": None,
        "summary": None,
        "email_sent": False,
        "email_status": "Waiting for analysis to complete..."
    }

    with jobs_lock:
        jobs[analysis_id] = job_record
        latest_analysis_id = analysis_id

    worker_thread = threading.Thread(
        target=execute_bitemporal_worker,
        args=(analysis_id, params, cancel_event),
        daemon=True
    )
    worker_thread.start()

    return jsonify({
        "status": "started",
        "analysis_id": analysis_id,
        "message": f"ForestWatch AI analysis {analysis_id} started in background"
    })


@app.route('/run-historical', methods=['POST'])
def start_historical_analysis():
    """Start a multi-year historical analysis job"""
    global latest_analysis_id

    payload = request.get_json(silent=True) or request.form or {}
    
    timestamp_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    analysis_id = f"hist_{timestamp_tag}_{rand_suffix}"

    params = {
        "latitude": float(payload.get("latitude", 15.0)),
        "longitude": float(payload.get("longitude", 75.0)),
        "start_year": int(payload.get("start_year", 2019)),
        "end_year": int(payload.get("end_year", 2024)),
        "radius_meters": float(payload.get("radius_meters", 1500)),
        "scale": int(payload.get("scale", 30))
    }

    cancel_event = threading.Event()

    job_record = {
        "id": analysis_id,
        "type": "historical",
        "status": "starting",
        "params": params,
        "messages": [f"Historical analysis {analysis_id} ({params['start_year']}-{params['end_year']}) queued..."],
        "cancel_event": cancel_event,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": None,
        "report_path": None,
        "chart_path": None,
        "summary": None,
        "email_sent": False,
        "email_status": "Not configured"
    }

    with jobs_lock:
        jobs[analysis_id] = job_record
        latest_analysis_id = analysis_id

    worker_thread = threading.Thread(
        target=execute_historical_worker,
        args=(analysis_id, params, cancel_event),
        daemon=True
    )
    worker_thread.start()

    return jsonify({
        "status": "started",
        "analysis_id": analysis_id,
        "message": f"Historical analysis {analysis_id} started in background"
    })


@app.route('/stop-analysis', methods=['POST'])
def stop_analysis():
    """Cancel a running analysis job cooperatively"""
    payload = request.get_json(silent=True) or request.form or {}
    analysis_id = payload.get("analysis_id") or latest_analysis_id

    job = get_job(analysis_id)
    if not job:
        return jsonify({"status": "not_found", "message": "No active analysis found"}), 404

    if job["status"] in ["running", "starting"]:
        job["cancel_event"].set()
        job["status"] = "cancelled"
        job["messages"].append("⏹ Analysis cancellation signal sent.")
        return jsonify({
            "status": "cancelled",
            "analysis_id": job["id"],
            "message": "Analysis cancellation confirmed"
        })
    else:
        return jsonify({
            "status": job["status"],
            "analysis_id": job["id"],
            "message": f"Job is already {job['status']}"
        })


@app.route('/status')
def get_status():
    """Get status of an analysis (by ID or latest)"""
    analysis_id = request.args.get("id") or latest_analysis_id
    job = get_job(analysis_id)

    if not job:
        return jsonify({
            "status": "idle",
            "messages": [],
            "analysis_id": None,
            "timestamp": None,
            "email_sent": False
        })

    rel_report = job.get("rel_report_path") or "sentinel_output/forest_analysis.txt"
    rel_chart = job.get("rel_chart_path") or "sentinel_output/forest_classification.png"
    rel_map = job.get("rel_map_path")

    return jsonify({
        "status": job["status"],
        "analysis_id": job["id"],
        "type": job.get("type", "bitemporal"),
        "messages": job["messages"],
        "timestamp": job["started_at"],
        "completed_at": job["completed_at"],
        "report_path": rel_report,
        "chart_path": rel_chart,
        "map_path": rel_map,
        "email_sent": job["email_sent"],
        "email_status": job["email_status"],
        "summary": job.get("summary")
    })


@app.route('/report')
def get_report():
    """Get the text report content for an analysis"""
    analysis_id = request.args.get("id") or latest_analysis_id
    job = get_job(analysis_id)

    if job and job.get("report_path") and os.path.exists(job["report_path"]):
        with open(job["report_path"], 'r') as f:
            content = f.read()
        return jsonify({"content": content, "analysis_id": job["id"]})

    shared_report = os.path.join(OUTPUT_ROOT, "forest_analysis.txt")
    if os.path.exists(shared_report):
        with open(shared_report, 'r') as f:
            content = f.read()
        return jsonify({"content": content, "analysis_id": "latest"})

    return jsonify({"content": "Report not available yet. Please run an analysis."})


@app.route('/chart')
def get_chart():
    """Get the latest chart filenames and URLs"""
    analysis_id = request.args.get("id") or latest_analysis_id
    job = get_job(analysis_id)

    if job and job.get("chart_path") and os.path.exists(job["chart_path"]):
        res = {
            "analysis_id": job["id"],
            "type": job.get("type", "bitemporal"),
            "chart_url": f"/static/{job['rel_chart_path']}",
            "filename": os.path.basename(job["chart_path"])
        }
        if job.get("rel_map_path"):
            res["map_url"] = f"/static/{job['rel_map_path']}"
        return jsonify(res)

    shared_chart = os.path.join(OUTPUT_ROOT, "forest_classification.png")
    if os.path.exists(shared_chart):
        return jsonify({
            "analysis_id": "latest",
            "chart_url": "/static/sentinel_output/forest_classification.png",
            "map_url": "/static/sentinel_output/temporal_comparison.png",
            "filename": "forest_classification.png"
        })

    return jsonify({"error": "Chart not available"}), 404


@app.route('/api/satellite-tiles')
def get_satellite_tiles():
    """Get live True-Color and NDVI tile layer URLs from Google Earth Engine"""
    try:
        lat = float(request.args.get("lat", 15.0))
        lon = float(request.args.get("lon", 75.0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid coordinates"}), 400

    import gee_data_loader
    data, err = gee_data_loader.get_sentinel2_tile_urls(lat, lon)
    if err or not data:
        return jsonify({
            "status": "fallback",
            "message": err or "Using high-resolution base layer",
            "acquisition_date": "Latest Available Satellite Observation",
            "cloud_percentage": 0.0,
            "data_source": "Copernicus Sentinel-2 / Satellite Archive",
            "quality_flag": "Standard"
        })

    return jsonify(data)


@app.route('/export/pdf/<analysis_id>')
def export_pdf(analysis_id):
    """Download executive PDF report for a given analysis"""
    target_dir = os.path.join(OUTPUT_ROOT, analysis_id)
    pdf_path = os.path.join(target_dir, f"forest_report_{analysis_id}.pdf")
    
    if os.path.exists(pdf_path):
        return send_file(pdf_path, as_attachment=True, download_name=f"ForestWatch_Report_{analysis_id}.pdf")
    return jsonify({"error": "PDF report not found for this analysis"}), 404


@app.route('/export/csv/<analysis_id>')
def export_csv(analysis_id):
    """Download CSV metrics for a given analysis"""
    target_dir = os.path.join(OUTPUT_ROOT, analysis_id)
    csv_path = os.path.join(target_dir, f"forest_data_{analysis_id}.csv")
    
    if os.path.exists(csv_path):
        return send_file(csv_path, as_attachment=True, download_name=f"ForestWatch_Metrics_{analysis_id}.csv")
    return jsonify({"error": "CSV file not found for this analysis"}), 404


@app.route('/analyses')
def list_analyses():
    """List all executed analyses with IDs and summary metrics"""
    with jobs_lock:
        items = []
        for aid, j in reversed(list(jobs.items())):
            summary = j.get("summary", {})
            change_stats = summary.get("change_stats", {}) if summary else {}
            items.append({
                "id": aid,
                "type": j.get("type", "bitemporal"),
                "status": j["status"],
                "started_at": j["started_at"],
                "completed_at": j["completed_at"],
                "coordinates": f"{j['params']['latitude']}, {j['params']['longitude']}",
                "deforested_pct": change_stats.get("deforested", {}).get("percentage", 0.0),
                "deforested_ha": change_stats.get("deforested", {}).get("hectares", 0.0),
                "risk_level": change_stats.get("risk_level", "N/A")
            })
        return jsonify({"analyses": items})


@app.route('/api/locations', methods=['GET', 'POST'])
def manage_locations():
    """Retrieve or save monitoring locations in saved_locations.json"""
    if request.method == 'GET':
        if os.path.exists(LOCATIONS_FILE):
            with open(LOCATIONS_FILE, 'r') as f:
                data = json.load(f)
            return jsonify({"locations": data})
        return jsonify({"locations": []})

    elif request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        name = payload.get("name", "").strip()
        if not name:
            return jsonify({"error": "Location name is required"}), 400

        try:
            lat = float(payload.get("latitude"))
            lon = float(payload.get("longitude"))
        except (TypeError, ValueError):
            return jsonify({"error": "Valid latitude and longitude required"}), 400

        new_loc = {
            "id": f"loc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}",
            "name": name,
            "region": payload.get("region", "Custom Monitored Zone"),
            "latitude": lat,
            "longitude": lon,
            "radius_meters": float(payload.get("radius_meters", 2000)),
            "description": payload.get("description", "User-defined monitoring boundary"),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "notes": payload.get("notes", "")
        }

        locations = []
        if os.path.exists(LOCATIONS_FILE):
            try:
                with open(LOCATIONS_FILE, 'r') as f:
                    locations = json.load(f)
            except Exception:
                locations = []

        locations.append(new_loc)
        with open(LOCATIONS_FILE, 'w') as f:
            json.dump(locations, f, indent=2)

        return jsonify({"status": "saved", "location": new_loc})


@app.route('/api/geocode', methods=['GET'])
def geocode_location():
    """
    Search for places, national parks, wildlife sanctuaries, and reserves.
    First checks saved_locations.json for instant local match, then uses Nominatim.
    """
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify({"results": []})

    matches = []

    # 1. Local saved locations match
    if os.path.exists(LOCATIONS_FILE):
        try:
            with open(LOCATIONS_FILE, 'r') as f:
                locs = json.load(f)
            for loc in locs:
                if query.lower() in loc["name"].lower() or query.lower() in loc.get("region", "").lower():
                    matches.append({
                        "name": loc["name"],
                        "latitude": loc["latitude"],
                        "longitude": loc["longitude"],
                        "display_name": f"{loc['name']}, {loc.get('region', '')}",
                        "source": "Saved Conservation Reserves",
                        "radius_meters": loc.get("radius_meters", 2000)
                    })
        except Exception as e:
            logger.warning(f"Error checking local locations: {e}")

    # 2. Geopy Nominatim lookup
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="forestwatch_ai_monitor", timeout=4)
        location = geolocator.geocode(query, exactly_one=False, limit=4)
        if location:
            for item in location:
                matches.append({
                    "name": item.address.split(',')[0],
                    "latitude": float(item.latitude),
                    "longitude": float(item.longitude),
                    "display_name": item.address,
                    "source": "OpenStreetMap Geocoding",
                    "radius_meters": 2000
                })
    except Exception as e:
        logger.warning(f"Geocoding service unavailable or timed out: {e}")

    return jsonify({"results": matches[:6]})


@app.route('/static/sentinel_output/<path:filename>')
def serve_sentinel_output(filename):
    """Serve output files from isolated subdirectories"""
    return send_from_directory(OUTPUT_ROOT, filename)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='127.0.0.1', port=port)
