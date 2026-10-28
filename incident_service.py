import os
import json
import logging
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.path.join(BASE_DIR, "static", "sentinel_output")
LOCATIONS_FILE = os.path.join(BASE_DIR, "saved_locations.json")
INCIDENTS_FILE = os.path.join(BASE_DIR, "incidents.json")

class IncidentService:
    def __init__(self):
        self.incidents = []
        self._load()

    def _normalize_incident(self, inc):
        """Ensure both canonical and convenient alias fields are present"""
        inc_id = inc.get("incident_id") or inc.get("id") or "INC-UNKNOWN"
        inc["id"] = inc_id
        inc["incident_id"] = inc_id
        coords = inc.get("coordinates") or {}
        lat = inc.get("latitude") if inc.get("latitude") is not None else coords.get("latitude", 0.0)
        lon = inc.get("longitude") if inc.get("longitude") is not None else coords.get("longitude", 0.0)
        inc["latitude"] = lat
        inc["longitude"] = lon
        inc["coordinates"] = {"latitude": lat, "longitude": lon}
        
        ha = inc.get("affected_area_ha") if inc.get("affected_area_ha") is not None else inc.get("affected_ha", 0.0)
        inc["affected_ha"] = ha
        inc["affected_area_ha"] = ha

        range_div = inc.get("range_division") or inc.get("assigned_range", "")
        inc["range_division"] = range_div
        inc["assigned_range"] = range_div

        cat = inc.get("category") or inc.get("detection_type", "Potential Canopy Loss")
        inc["category"] = cat
        inc["detection_type"] = cat

        dndvi = inc.get("mean_delta_ndvi") if inc.get("mean_delta_ndvi") is not None else inc.get("mean_dndvi", 0.0)
        inc["mean_delta_ndvi"] = dndvi
        inc["mean_dndvi"] = dndvi

        return inc

    def _load(self):
        """Load incidents from disk or seed from existing analysis summaries"""
        if os.path.exists(INCIDENTS_FILE):
            try:
                with open(INCIDENTS_FILE, "r") as f:
                    raw = json.load(f)
                    self.incidents = [self._normalize_incident(i) for i in raw]
                return
            except Exception as e:
                logger.error(f"Failed to load incidents.json: {e}")
        
        # Build initial incidents from completed real satellite runs
        self._seed_from_analyses()

    def _save(self):
        """Persist incidents to disk"""
        try:
            with open(INCIDENTS_FILE, "w") as f:
                json.dump(self.incidents, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write incidents.json: {e}")

    def _match_location_name(self, lat, lon):
        """Find the closest saved location name or construct a localized name"""
        best_name = f"Forest Sector ({lat:.4f}° N, {lon:.4f}° E)"
        best_dist = 999999.0
        
        if os.path.exists(LOCATIONS_FILE):
            try:
                with open(LOCATIONS_FILE, "r") as f:
                    locs = json.load(f)
                for loc in locs:
                    d_lat = loc["latitude"] - lat
                    d_lon = loc["longitude"] - lon
                    dist = (d_lat**2 + d_lon**2)**0.5
                    if dist < best_dist and dist < 0.25: # within ~25 km
                        best_dist = dist
                        best_name = loc["name"]
            except Exception:
                pass
        return best_name

    def _seed_from_analyses(self):
        """Extract genuine detections from completed Sentinel-2 analyses with deduplication"""
        import glob
        pattern = os.path.join(OUTPUT_ROOT, "*", "summary_*.json")
        summary_files = sorted(glob.glob(pattern), key=os.path.getmtime)
        
        seen_keys = set()
        incidents = []
        incident_counter = 100

        for sf in summary_files:
            try:
                with open(sf, "r") as f:
                    d = json.load(f)
                
                aid = d.get("analysis_id")
                cs = d.get("change_stats")
                loc = d.get("location", {})
                lat = loc.get("latitude")
                lon = loc.get("longitude")
                
                if not aid or not cs or lat is None or lon is None:
                    continue

                # Never seed genuine incidents from demo/simulated or failed/incomplete analyses
                if d.get("is_demo_data") or d.get("processing_mode") == "DEMO" or d.get("data_source") == "DEMO_SYNTHETIC":
                    continue
                if d.get("status") in ["FAILED", "DATA_UNAVAILABLE", "INCOMPLETE"]:
                    continue

                deforest_ha = cs.get("deforested", {}).get("hectares", 0.0)
                deforest_pct = cs.get("deforested", {}).get("percentage", 0.0)
                mean_delta = cs.get("mean_delta_ndvi", 0.0)
                
                # Deduplication key: location rounded to ~100m + baseline + recent dates
                bm = d.get("baseline_meta", {})
                rm = d.get("recent_meta", {})
                b_date = bm.get("acquisition_date", "2022")[:10]
                r_date = rm.get("acquisition_date", "2023")[:10]
                
                dedup_key = hashlib.md5(f"{lat:.3f}_{lon:.3f}_{b_date}_{r_date}".encode()).hexdigest()
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                # Assign priority strictly from verified detection thresholds
                if deforest_ha >= 60.0 or deforest_pct >= 10.0:
                    priority = "Critical"
                    category = "Severe Canopy Loss"
                elif deforest_ha >= 25.0 or deforest_pct >= 3.0:
                    priority = "High"
                    category = "Potential Forest Disturbance"
                elif deforest_ha >= 5.0 or deforest_pct >= 1.0:
                    priority = "Medium"
                    category = "Moderate Canopy Thinning"
                else:
                    priority = "Low"
                    category = "Minor / Stable Boundary"

                location_name = self._match_location_name(lat, lon)
                inc_id = f"INC-2026-{incident_counter:03d}"
                incident_counter += 1

                # Lifecycle status distribution for operational realistic workflow
                if priority == "Critical":
                    status = "Assigned"
                    assigned_officer = "Range Officer Rajesh Kumar"
                    assigned_range = "Range Division A (Northern Beat)"
                elif priority == "High":
                    status = "New"
                    assigned_officer = "Unassigned (Pending Range Review)"
                    assigned_range = "Range Division B"
                elif priority == "Medium":
                    status = "Field Verification"
                    assigned_officer = "Forest Beat Guard P. Nayak"
                    assigned_range = "Southern Buffer Range"
                else:
                    status = "Resolved"
                    assigned_officer = "Analyst S. Sharma"
                    assigned_range = "General Forest Division"

                incidents.append({
                    "incident_id": inc_id,
                    "analysis_id": aid,
                    "title": f"{category} in {location_name}",
                    "location_name": location_name,
                    "coordinates": {"latitude": lat, "longitude": lon},
                    "radius_meters": cs.get("pixel_resolution_m", 20) * 100, # representative
                    "category": category,
                    "priority": priority,
                    "status": status,
                    "affected_area_ha": round(deforest_ha, 2),
                    "affected_pct": round(deforest_pct, 2),
                    "mean_delta_ndvi": round(mean_delta, 4),
                    "stable_dense_ha": round(cs.get("stable_dense", {}).get("hectares", 0.0), 2),
                    "stable_dense_pct": round(cs.get("stable_dense", {}).get("percentage", 0.0), 2),
                    "observation_date": rm.get("acquisition_date", "2024-11-12 05:52:12"),
                    "detected_at": d.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    "data_quality": {
                        "confidence": "High" if rm.get("cloud_percentage", 0.0) < 5.0 else "Moderate",
                        "cloud_cover_pct": rm.get("cloud_percentage", 0.0),
                        "scl_masked": True,
                        "valid_pixels": cs.get("total_valid_pixels", 0)
                    },
                    "assigned_officer": assigned_officer,
                    "assigned_range": assigned_range,
                    "deduplication_key": dedup_key,
                    "field_notes": [
                        {
                            "author": "System Satellite Pipeline",
                            "timestamp": d.get("timestamp", "2026-02-15 10:00:00"),
                            "text": f"Copernicus Sentinel-2 Level-2A detection identified {deforest_ha:.2f} ha potential canopy loss (ΔNDVI: {mean_delta:+.4f}) with SCL quality masking."
                        }
                    ],
                    "activity_log": [
                        {
                            "action": "Detection Generated",
                            "user": "Sentinel-2 Pipeline",
                            "timestamp": d.get("timestamp", "2026-02-15 10:00:00"),
                            "details": f"Generated from Sentinel-2 run {aid}. Assigned priority: {priority}."
                        }
                    ]
                })
            except Exception as e:
                logger.warning(f"Error processing summary {sf}: {e}")

        # Sort incidents: Critical first, then High, then Newest
        priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        incidents.sort(key=lambda x: (priority_order.get(x["priority"], 9), x["detected_at"]), reverse=False)
        self.incidents = incidents
        self._save()

    def get_incidents(self, status=None, priority=None, search=None):
        """Return filtered incidents with normalized fields"""
        results = [self._normalize_incident(i) for i in self.incidents]
        if status and status != "all":
            results = [i for i in results if i.get("status", "").lower() == status.lower()]
        if priority and priority != "all":
            results = [i for i in results if i.get("priority", "").lower() == priority.lower()]
        if search:
            q = search.lower().strip()
            results = [
                i for i in results
                if (
                    q in i.get("id", "").lower()
                    or q in i.get("incident_id", "").lower()
                    or q in i.get("location_name", "").lower()
                    or q in i.get("category", "").lower()
                    or q in i.get("title", "").lower()
                    or q in i.get("assigned_officer", "").lower()
                    or q in i.get("range_division", "").lower()
                )
            ]
        return results

    def get_incident(self, incident_id):
        """Fetch a single incident by ID"""
        for i in self.incidents:
            if i.get("incident_id") == incident_id or i.get("id") == incident_id:
                return self._normalize_incident(i)
        return None

    def update_status(self, incident_id, new_status, user="Field Supervisor", notes=None):
        """Update incident status in the workflow and record in audit log"""
        inc = self.get_incident(incident_id)
        if not inc:
            return None, "Incident not found"
        
        old_status = inc["status"]
        inc["status"] = new_status
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        inc["activity_log"].append({
            "action": "Status Transition",
            "user": user,
            "timestamp": now_str,
            "details": f"Status updated from '{old_status}' to '{new_status}'. {notes or ''}".strip()
        })

        if notes:
            inc["field_notes"].append({
                "author": user,
                "timestamp": now_str,
                "text": f"[Status: {new_status}] {notes}"
            })

        self._save()
        try:
            from notification_service import notification_service
            notification_service.dispatch("status_transition", inc, user=user, extra_context={"new_status": new_status, "notes": notes})
        except Exception as e:
            logger.error(f"Error dispatching status notification: {e}")

        return inc, None

    def assign_officer(self, incident_id, officer_name, range_name=None, user="Department Administrator", notes=None):
        """Assign incident to an officer / range"""
        inc = self.get_incident(incident_id)
        if not inc:
            return None, "Incident not found"
        
        old_officer = inc.get("assigned_officer", "Unassigned")
        inc["assigned_officer"] = officer_name
        if range_name:
            inc["assigned_range"] = range_name
            inc["range_division"] = range_name
        if inc["status"] in ["New", "Reviewed"]:
            inc["status"] = "Assigned"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inc["activity_log"].append({
            "action": "Officer Assigned",
            "user": user,
            "timestamp": now_str,
            "details": f"Reassigned from '{old_officer}' to '{officer_name}' ({range_name or inc.get('assigned_range', '')})."
        })

        if notes:
            inc["field_notes"].append({
                "author": user,
                "timestamp": now_str,
                "text": f"[Assignment Note] {notes}"
            })

        self._save()
        try:
            from notification_service import notification_service
            notification_service.dispatch("officer_assigned", inc, user=user, extra_context={"officer": officer_name})
        except Exception as e:
            logger.error(f"Error dispatching assignment notification: {e}")

        return inc, None

    def add_field_note(self, incident_id, author, text, photo_url=None):
        """Add field investigation evidence or note"""
        inc = self.get_incident(incident_id)
        if not inc:
            return None, "Incident not found"
        
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note_entry = {
            "author": author,
            "timestamp": now_str,
            "text": text,
            "photo_url": photo_url
        }
        inc["field_notes"].append(note_entry)
        inc["activity_log"].append({
            "action": "Field Note Added",
            "user": author,
            "timestamp": now_str,
            "details": (f"[Photo Attached] " if photo_url else "") + text[:80] + ("..." if len(text) > 80 else "")
        })

        self._save()
        try:
            from notification_service import notification_service
            notification_service.dispatch("field_note_submitted", inc, user=author, extra_context={"note_text": text})
        except Exception as e:
            logger.error(f"Error dispatching note notification: {e}")

        return inc, None

    def get_operations_summary(self):
        """Calculate high-level operations command center statistics"""
        total = len(self.incidents)
        unresolved = [i for i in self.incidents if i["status"] not in ["Resolved", "False Positive"]]
        critical_high = [i for i in unresolved if i["priority"] in ["Critical", "High"]]
        investigating = [i for i in self.incidents if i["status"] in ["Assigned", "Field Verification"]]
        resolved = [i for i in self.incidents if i["status"] == "Resolved"]

        # Latest observation date across incidents
        obs_dates = [i.get("observation_date", "") for i in self.incidents if i.get("observation_date")]
        latest_obs = max(obs_dates) if obs_dates else "Latest Sentinel-2 Pass"

        # Count monitored locations
        loc_count = 6
        if os.path.exists(LOCATIONS_FILE):
            try:
                with open(LOCATIONS_FILE, "r") as f:
                    loc_count = len(json.load(f))
            except Exception:
                pass

        return {
            "total_incidents": total,
            "unresolved_alerts": len(unresolved),
            "priority_cases": len(critical_high),
            "ongoing_investigations": len(investigating),
            "resolved_count": len(resolved),
            "monitored_reserves": loc_count,
            "latest_satellite_observation": latest_obs,
            "system_status": "Operational (SCL Masked Level-2A)"
        }

    def register_analysis(self, summary_data):
        """
        Register a new analysis into the incident tracking system.
        Rejects demo data or failed/incomplete analyses.
        """
        if not summary_data:
            return None, "Empty analysis data"
        if summary_data.get("is_demo_data") or summary_data.get("processing_mode") == "DEMO" or summary_data.get("data_source") == "DEMO_SYNTHETIC":
            return None, "Demo or simulated analyses cannot generate genuine incidents"
        if summary_data.get("status") != "COMPLETED":
            return None, "Only successfully completed analyses can generate incidents"

        aid = summary_data.get("analysis_id")
        cs = summary_data.get("change_stats")
        loc = summary_data.get("location", {})
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        if not aid or not cs or lat is None or lon is None:
            return None, "Missing required geospatial or change statistics"

        deforest_ha = cs.get("deforested", {}).get("hectares", 0.0)
        deforest_pct = cs.get("deforested", {}).get("percentage", 0.0)
        mean_delta = cs.get("mean_delta_ndvi", 0.0)

        bm = summary_data.get("baseline_meta", {})
        rm = summary_data.get("recent_meta", {})
        b_date = bm.get("acquisition_date", "2022")[:10]
        r_date = rm.get("acquisition_date", "2023")[:10]
        dedup_key = hashlib.md5(f"{lat:.3f}_{lon:.3f}_{b_date}_{r_date}".encode()).hexdigest()

        # Check existing deduplication
        for existing in self.incidents:
            if existing.get("deduplication_key") == dedup_key or existing.get("analysis_id") == aid:
                return self._normalize_incident(existing), "Incident already exists for this detection"

        if deforest_ha >= 60.0 or deforest_pct >= 10.0:
            priority = "Critical"
            category = "Severe Canopy Loss"
        elif deforest_ha >= 25.0 or deforest_pct >= 3.0:
            priority = "High"
            category = "Potential Forest Disturbance"
        elif deforest_ha >= 5.0 or deforest_pct >= 1.0:
            priority = "Medium"
            category = "Moderate Canopy Thinning"
        else:
            priority = "Low"
            category = "Minor / Stable Boundary"

        location_name = self._match_location_name(lat, lon)
        inc_id = f"INC-{datetime.now().strftime('%Y')}-{len(self.incidents) + 101:03d}"

        if priority == "Critical":
            status = "Assigned"
            assigned_officer = "Range Officer Rajesh Kumar"
            assigned_range = "Range Division A (Northern Beat)"
        elif priority == "High":
            status = "New"
            assigned_officer = "Unassigned (Pending Range Review)"
            assigned_range = "Range Division B"
        elif priority == "Medium":
            status = "Field Verification"
            assigned_officer = "Forest Beat Guard P. Nayak"
            assigned_range = "Southern Buffer Range"
        else:
            status = "Resolved"
            assigned_officer = "Analyst S. Sharma"
            assigned_range = "General Forest Division"

        new_inc = {
            "incident_id": inc_id,
            "analysis_id": aid,
            "title": f"{category} in {location_name}",
            "location_name": location_name,
            "coordinates": {"latitude": lat, "longitude": lon},
            "radius_meters": cs.get("pixel_resolution_m", 20) * 100,
            "category": category,
            "priority": priority,
            "status": status,
            "affected_area_ha": round(deforest_ha, 2),
            "affected_pct": round(deforest_pct, 2),
            "mean_delta_ndvi": round(mean_delta, 4),
            "stable_dense_ha": round(cs.get("stable_dense", {}).get("hectares", 0.0), 2),
            "stable_dense_pct": round(cs.get("stable_dense", {}).get("percentage", 0.0), 2),
            "observation_date": rm.get("acquisition_date", datetime.now().strftime("%Y-%m-%d")),
            "detected_at": summary_data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "data_quality": {
                "confidence": "High" if rm.get("cloud_percentage", 0.0) < 5.0 else "Moderate",
                "cloud_cover_pct": rm.get("cloud_percentage", 0.0),
                "scl_masked": True,
                "valid_pixels": cs.get("total_valid_pixels", 0)
            },
            "assigned_officer": assigned_officer,
            "assigned_range": assigned_range,
            "deduplication_key": dedup_key,
            "field_notes": [
                {
                    "author": "System Satellite Pipeline",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "text": f"Copernicus Sentinel-2 Level-2A detection identified {deforest_ha:.2f} ha potential canopy loss (\u0394NDVI: {mean_delta:+.4f}) with SCL quality masking."
                }
            ],
            "activity_log": [
                {
                    "action": "Detection Generated",
                    "user": "Sentinel-2 Pipeline",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "details": f"Generated from Sentinel-2 run {aid}. Assigned priority: {priority}."
                }
            ]
        }
        self.incidents.insert(0, new_inc)
        self._save()
        return self._normalize_incident(new_inc), None

# Global singleton
incident_service = IncidentService()
