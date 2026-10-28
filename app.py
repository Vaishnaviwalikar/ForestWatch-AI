from flask import Flask, render_template, jsonify, request, send_from_directory, send_file, redirect, url_for, session
import os
import sys
import json
import logging
import threading
import uuid
from datetime import datetime
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

from rbac import (
    require_role,
    get_current_user,
    AUTHORIZED_USERS,
    ALL_ROLES,
    ROLE_ADMIN,
    ROLE_RANGE_OFFICER,
    ROLE_FIELD_OFFICER,
    ROLE_ANALYST
)
from notification_service import notification_service

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()])
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "forestwatch-ops-secret-2026")

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.path.join(BASE_DIR, "static", "sentinel_output")
LOCATIONS_FILE = os.path.join(BASE_DIR, "saved_locations.json")
EVIDENCE_UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads", "evidence")
os.makedirs(OUTPUT_ROOT, exist_ok=True)
os.makedirs(EVIDENCE_UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

# Thread-safe in-memory registry of analyses
jobs_lock = threading.Lock()
jobs = {}
latest_analysis_id = None


def load_existing_runs_from_disk():
    """Preload completed analysis runs from disk so results persist across restarts"""
    global latest_analysis_id
    import glob
    pattern = os.path.join(OUTPUT_ROOT, "*", "summary_*.json")
    summary_files = sorted(glob.glob(pattern), key=os.path.getmtime)
    for sf in summary_files:
        try:
            with open(sf, 'r') as f:
                data = json.load(f)
            aid = data.get("analysis_id")
            if not aid:
                continue
            run_dir = os.path.join(OUTPUT_ROOT, aid)
            report_path = os.path.join(run_dir, f"forest_analysis_{aid}.txt")
            if not os.path.exists(report_path):
                report_path = os.path.join(OUTPUT_ROOT, "forest_analysis.txt")

            chart_path = os.path.join(run_dir, f"forest_classification_{aid}.png")
            if not os.path.exists(chart_path):
                chart_path = os.path.join(OUTPUT_ROOT, "forest_classification.png")

            map_path = os.path.join(run_dir, f"temporal_comparison_{aid}.png")
            if not os.path.exists(map_path):
                map_path = os.path.join(OUTPUT_ROOT, "temporal_comparison.png")

            pdf_path = os.path.join(run_dir, f"forest_report_{aid}.pdf")
            csv_path = os.path.join(run_dir, f"forest_data_{aid}.csv")

            is_hist = aid.startswith("hist_") or data.get("type") == "historical"
            job_type = "historical" if is_hist else "bitemporal"

            lat = data.get("location", {}).get("latitude", 15.0)
            lon = data.get("location", {}).get("longitude", 75.0)

            job_record = {
                "id": aid,
                "type": job_type,
                "status": "completed",
                "params": {
                    "latitude": lat,
                    "longitude": lon,
                    "baseline_start": data.get("baseline_meta", {}).get("query_start_date", "2022-01-01"),
                    "baseline_end": data.get("baseline_meta", {}).get("query_end_date", "2022-05-31"),
                    "recent_start": data.get("recent_meta", {}).get("query_start_date", "2023-01-01"),
                    "recent_end": data.get("recent_meta", {}).get("query_end_date", "2023-05-31"),
                    "radius_meters": 2000,
                    "scale": 20
                },
                "messages": ["Analysis loaded from persistent storage."],
                "cancel_event": threading.Event(),
                "started_at": data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                "completed_at": data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                "report_path": report_path if os.path.exists(report_path) else None,
                "chart_path": chart_path if os.path.exists(chart_path) else None,
                "map_path": map_path if os.path.exists(map_path) else None,
                "pdf_path": pdf_path if os.path.exists(pdf_path) else None,
                "csv_path": csv_path if os.path.exists(csv_path) else None,
                "rel_report_path": f"sentinel_output/{aid}/forest_analysis_{aid}.txt" if os.path.exists(report_path) else "sentinel_output/forest_analysis.txt",
                "rel_chart_path": f"sentinel_output/{aid}/forest_classification_{aid}.png" if os.path.exists(chart_path) else "sentinel_output/forest_classification.png",
                "rel_map_path": f"sentinel_output/{aid}/temporal_comparison_{aid}.png" if os.path.exists(map_path) else "sentinel_output/temporal_comparison.png",
                "summary": data,
                "email_sent": False,
                "email_status": "Completed"
            }
            with jobs_lock:
                jobs[aid] = job_record
                latest_analysis_id = aid
        except Exception as e:
            logger.warning(f"Error loading summary {sf}: {e}")

load_existing_runs_from_disk()


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

        # Register genuine analysis in incident tracking (rejects demo/failed runs)
        if not result.get("summary", {}).get("is_demo_data", False):
            try:
                from incident_service import incident_service
                incident_service.register_analysis(result["summary"])
            except Exception as e:
                logger.warning(f"Could not register incident for analysis {analysis_id}: {e}")

    except InterruptedError:
        with jobs_lock:
            job["status"] = "cancelled"
            job["messages"].append("⏹ Analysis was cancelled by user.")
        logger.info(f"Analysis {analysis_id} successfully cancelled.")

    except Exception as e:
        with jobs_lock:
            job["status"] = "failed" if "DATA_UNAVAILABLE" in str(e) else "error"
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
            job["status"] = "failed" if "DATA_UNAVAILABLE" in str(e) else "error"
            job["messages"].append(f"❌ Error: {str(e)}")
        logger.error(f"Error in historical analysis {analysis_id}: {str(e)}", exc_info=True)


@app.route('/')
def feature_selection():
    """Render the ForestWatch AI Feature Selection Hub (RoadSafe AI inspired)"""
    return render_template('feature_selection.html')


@app.route('/dashboard')
def dashboard():
    """Render the internal ForestWatch AI monitoring workspaces"""
    return render_template('index.html')


@app.route('/explorer')
def view_explorer():
    return redirect(url_for('dashboard', view='explorer'))


@app.route('/vegetation')
def view_vegetation():
    return redirect(url_for('dashboard', view='vegetation'))


@app.route('/change')
def view_change():
    return redirect(url_for('dashboard', view='change'))


@app.route('/historical')
def view_historical():
    return redirect(url_for('dashboard', view='historical'))


@app.route('/reports')
def view_reports():
    return redirect(url_for('dashboard', view='reports'))


@app.route('/overview')
def view_overview():
    return redirect(url_for('dashboard', view='overview'))


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
        "scale": int(payload.get("scale", 20)),
        "demo_mode": bool(payload.get("demo_mode", False))
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
        "scale": int(payload.get("scale", 30)),
        "demo_mode": bool(payload.get("demo_mode", False))
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


from incident_service import incident_service


@app.route('/api/operations/summary')
def get_operations_summary():
    """Retrieve operational command center summary KPIs"""
    return jsonify(incident_service.get_operations_summary())


@app.route('/api/incidents', methods=['GET'])
def get_incidents():
    """List operational alerts and incidents with filters"""
    status = request.args.get("status")
    priority = request.args.get("priority")
    search = request.args.get("search") or request.args.get("q")
    incidents = incident_service.get_incidents(status=status, priority=priority, search=search)
    return jsonify({"incidents": incidents, "count": len(incidents)})


@app.route('/api/incidents/<incident_id>', methods=['GET'])
def get_incident_detail(incident_id):
    """Retrieve complete incident details, source analysis, and audit log"""
    inc = incident_service.get_incident(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    aid = inc.get("analysis_id")
    if aid:
        inc["map_url"] = f"/static/sentinel_output/{aid}/temporal_comparison_{aid}.png"
        inc["chart_url"] = f"/static/sentinel_output/{aid}/forest_classification_{aid}.png"
        inc["report_url"] = f"/report?id={aid}"
        inc["pdf_url"] = f"/export/pdf/{aid}"
        inc["csv_url"] = f"/export/csv/{aid}"

    res = dict(inc)
    res["incident"] = inc
    return jsonify(res)


@app.route('/api/incidents/<incident_id>/status', methods=['POST'])
@require_role([ROLE_ADMIN, ROLE_RANGE_OFFICER, ROLE_FIELD_OFFICER])
def update_incident_status(incident_id):
    """Update incident workflow status (New -> Assigned -> Field Verification -> Resolved)"""
    payload = request.get_json(silent=True) or request.form or {}
    new_status = payload.get("status")
    if not new_status:
        return jsonify({"error": "Status is required"}), 400

    curr_user = get_current_user()
    user = payload.get("user") or curr_user.get("name", "Field Supervisor")
    notes = payload.get("notes") or payload.get("note") or ""
    inc, err = incident_service.update_status(incident_id, new_status, user=user, notes=notes)
    if err:
        return jsonify({"error": err}), 404
    res = dict(inc)
    res["incident"] = inc
    res["status_action"] = "updated"
    return jsonify(res)


@app.route('/api/incidents/<incident_id>/assign', methods=['POST'])
@require_role([ROLE_ADMIN, ROLE_RANGE_OFFICER])
def assign_incident_officer(incident_id):
    """Assign incident to an officer or range team"""
    payload = request.get_json(silent=True) or request.form or {}
    officer = payload.get("officer")
    if not officer:
        return jsonify({"error": "Officer name is required"}), 400

    range_name = payload.get("range", "")
    curr_user = get_current_user()
    user = payload.get("user") or curr_user.get("name", "Department Administrator")
    notes = payload.get("notes") or payload.get("note") or ""

    inc, err = incident_service.assign_officer(incident_id, officer, range_name=range_name, user=user, notes=notes)
    if err:
        return jsonify({"error": err}), 404
    res = dict(inc)
    res["incident"] = inc
    res["status_action"] = "assigned"
    return jsonify(res)


@app.route('/api/incidents/<incident_id>/notes', methods=['POST'])
@require_role([ROLE_ADMIN, ROLE_RANGE_OFFICER, ROLE_FIELD_OFFICER])
def add_incident_note(incident_id):
    """Add field investigation evidence or notes"""
    payload = request.get_json(silent=True) or request.form or {}
    curr_user = get_current_user()
    author = payload.get("author") or curr_user.get("name", "Field Officer")
    text = payload.get("text", "").strip()
    if not text:
        return jsonify({"error": "Note text is required"}), 400

    photo_url = payload.get("photo_url")
    inc, err = incident_service.add_field_note(incident_id, author, text, photo_url=photo_url)
    if err:
        return jsonify({"error": err}), 404
    res = dict(inc)
    res["incident"] = inc
    res["status_action"] = "saved"
    return jsonify(res)


@app.route('/api/incidents/<incident_id>/upload-photo', methods=['POST'])
@require_role([ROLE_ADMIN, ROLE_RANGE_OFFICER, ROLE_FIELD_OFFICER])
def upload_incident_photo(incident_id):
    """Upload ground-truthing photographic evidence for an incident"""
    inc = incident_service.get_incident(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    if 'photo' not in request.files:
        return jsonify({"error": "No photo file provided in request ('photo' field required)"}), 400

    file = request.files['photo']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    caption = request.form.get("caption", "").strip() or "Ground-truthing photographic evidence"
    curr_user = get_current_user()
    author = request.form.get("author") or curr_user.get("name", "Field Officer")

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Invalid image format '{ext}'. Allowed: {sorted(list(ALLOWED_EXTENSIONS))}"}), 400

    incident_dir = os.path.join(EVIDENCE_UPLOAD_DIR, incident_id)
    os.makedirs(incident_dir, exist_ok=True)

    safe_name = secure_filename(file.filename)
    unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}_{safe_name}"
    save_path = os.path.join(incident_dir, unique_filename)
    file.save(save_path)

    relative_url = f"/static/uploads/evidence/{incident_id}/{unique_filename}"
    inc, err = incident_service.add_field_note(incident_id, author=author, text=caption, photo_url=relative_url)
    if err:
        return jsonify({"error": err}), 404

    res = dict(inc)
    res["incident"] = inc
    res["photo_url"] = relative_url
    res["status_action"] = "photo_uploaded"
    return jsonify(res)


@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    """List notification delivery audit trail"""
    incident_id = request.args.get("incident_id")
    channel = request.args.get("channel")
    limit = int(request.args.get("limit", 50))
    logs = notification_service.get_audit_trail(incident_id=incident_id, channel=channel, limit=limit)
    return jsonify({
        "notifications": logs,
        "count": len(logs),
        "test_mode": notification_service.test_mode
    })


@app.route('/api/notifications/test', methods=['POST'])
@require_role([ROLE_ADMIN, ROLE_RANGE_OFFICER])
def test_notification():
    """Trigger a safe test notification in test mode across configured channels"""
    payload = request.get_json(silent=True) or request.form or {}
    incident_id = payload.get("incident_id")
    curr_user = get_current_user()

    if incident_id:
        inc = incident_service.get_incident(incident_id)
    else:
        incidents = incident_service.get_incidents()
        inc = incidents[0] if incidents else {
            "id": "INC-TEST",
            "location_name": "Surveillance Test Reserve",
            "priority": "High",
            "affected_ha": 35.5
        }

    results = notification_service.dispatch(
        event_type="new_alert",
        incident=inc,
        user=curr_user.get("name", "Test Officer"),
        force=True
    )
    return jsonify({
        "status": "success",
        "message": f"Dispatched {len(results)} simulated test notifications.",
        "results": results,
        "test_mode": notification_service.test_mode
    })


@app.route('/api/notifications/recipients', methods=['GET'])
def get_notification_recipients():
    """Get registered notification recipients and priority thresholds"""
    return jsonify({
        "recipients": notification_service.recipients,
        "test_mode": notification_service.test_mode
    })


@app.route('/api/auth/current-user', methods=['GET'])
def get_auth_user():
    """Get active session user identity, role, badge and permissions"""
    user = get_current_user()
    return jsonify({
        "user": user,
        "available_roles": ALL_ROLES,
        "authorized_users": list(AUTHORIZED_USERS.values())
    })


@app.route('/api/auth/switch-role', methods=['POST'])
def switch_auth_role():
    """Switch active operational role (for testing and field workflow simulation)"""
    payload = request.get_json(silent=True) or request.form or {}
    role = payload.get("role")
    name = payload.get("name")
    
    if not role:
        return jsonify({"error": "Role is required"}), 400

    session["user_role"] = role
    if name:
        session["user_name"] = name
    else:
        for u in AUTHORIZED_USERS.values():
            if u["role"] == role:
                session["user_name"] = u["name"]
                break

    user = get_current_user()
    return jsonify({
        "status": "switched",
        "current_user": user
    })


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
