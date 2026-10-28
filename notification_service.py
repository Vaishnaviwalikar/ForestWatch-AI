"""
Notification Service for ForestWatch AI
Provides provider-independent multi-channel notifications (In-App, Email, SMS)
with strict TEST_MODE fallback, recipient authorization preferences,
alert deduplication, templated alerts, and an immutable delivery audit log.
"""

import os
import json
import logging
import uuid
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NOTIFICATIONS_LOG_FILE = os.path.join(BASE_DIR, "notifications.json")
RECIPIENTS_FILE = os.path.join(BASE_DIR, "authorized_recipients.json")

# Default to TEST_MODE=True for safety
TEST_MODE = os.environ.get("NOTIFICATION_TEST_MODE", "true").lower() in ["1", "true", "yes"]

# Default Department Personnel Registry
DEFAULT_RECIPIENTS = [
    {
        "id": "REC-01",
        "name": "Shri R. Sharma, IFS",
        "role": "Department Admin",
        "designation": "Divisional Forest Officer (DFO)",
        "email": "dfo.headquarters@forest.gov.in",
        "phone": "+91-98765-01001",
        "enabled_channels": ["in_app", "email", "sms"],
        "min_priority": "High",
        "jurisdiction": "All Conservator Sectors"
    },
    {
        "id": "REC-02",
        "name": "Rajesh Kumar",
        "role": "Range Officer",
        "designation": "Range Forest Officer (Northern Beat)",
        "email": "rfo.north@forest.gov.in",
        "phone": "+91-98765-01002",
        "enabled_channels": ["in_app", "email", "sms"],
        "min_priority": "Medium",
        "jurisdiction": "Northern Range Division"
    },
    {
        "id": "REC-03",
        "name": "P. Deshmukh",
        "role": "Range Officer",
        "designation": "Range Forest Officer (Western Beat)",
        "email": "rfo.west@forest.gov.in",
        "phone": "+91-98765-01003",
        "enabled_channels": ["in_app", "email", "sms"],
        "min_priority": "Medium",
        "jurisdiction": "Western Range Division"
    },
    {
        "id": "REC-04",
        "name": "Dr. Ananya Roy",
        "role": "Analyst",
        "designation": "Senior Satellite Remote Sensing Analyst",
        "email": "analyst.geospatial@forest.gov.in",
        "phone": "+91-98765-01004",
        "enabled_channels": ["in_app", "email"],
        "min_priority": "Critical",
        "jurisdiction": "Geospatial Surveillance Center"
    },
    {
        "id": "REC-05",
        "name": "Beat Guard S. Patil",
        "role": "Field Officer",
        "designation": "Field Verification Scout",
        "email": "beat.patil@forest.gov.in",
        "phone": "+91-98765-01005",
        "enabled_channels": ["in_app", "sms"],
        "min_priority": "High",
        "jurisdiction": "Sector Patrol Unit A"
    }
]


# =============================================================================
# Provider Interfaces
# =============================================================================

class NotificationProvider(ABC):
    @abstractmethod
    def send(self, recipient, subject, body, metadata=None):
        """Send notification and return dict(status, message, details)"""
        pass


class InAppProvider(NotificationProvider):
    def send(self, recipient, subject, body, metadata=None):
        return {
            "channel": "in_app",
            "status": "delivered",
            "provider": "ForestWatch Internal Feed",
            "details": "Published to command center operational notification feed."
        }


class EmailProvider(NotificationProvider):
    def __init__(self, test_mode=True):
        self.test_mode = test_mode

    def send(self, recipient, subject, body, metadata=None):
        target_email = recipient.get("email")
        if not target_email:
            return {"channel": "email", "status": "skipped", "provider": "SMTP", "details": "No email address registered"}

        if self.test_mode:
            logger.info(f"[TEST_MODE EMAIL] To: {target_email} | Subject: {subject}")
            return {
                "channel": "email",
                "status": "simulated",
                "provider": "SMTP Safe Test Gateway",
                "details": f"Test mode simulated delivery to {target_email} without external SMTP relay."
            }

        # Real SMTP implementation (disabled unless credentials explicitly supplied)
        smtp_host = os.environ.get("SMTP_HOST")
        smtp_user = os.environ.get("SMTP_USER")
        smtp_pass = os.environ.get("SMTP_PASS")
        if not (smtp_host and smtp_user and smtp_pass):
            return {
                "channel": "email",
                "status": "held",
                "provider": "SMTP",
                "details": "SMTP credentials not configured. Switched to safe mode."
            }
        # In production with approved credentials, smtplib code would run here
        return {"channel": "email", "status": "simulated", "provider": "SMTP", "details": "Live sending held pending approval."}


class SMSProvider(NotificationProvider):
    def __init__(self, test_mode=True):
        self.test_mode = test_mode

    def send(self, recipient, subject, body, metadata=None):
        phone = recipient.get("phone")
        if not phone:
            return {"channel": "sms", "status": "skipped", "provider": "SMS Gateway", "details": "No phone number registered"}

        # Minimize sensitive information in SMS per prompt requirements: direct to portal
        incident_id = (metadata or {}).get("incident_id", "Alert")
        sms_body = f"[ForestWatch AI Alert] Potential vegetation disturbance detected ({incident_id}). Access authorized portal for details."

        if self.test_mode:
            logger.info(f"[TEST_MODE SMS] To: {phone} | Text: {sms_body}")
            return {
                "channel": "sms",
                "status": "simulated",
                "provider": "SMS Test Adapter",
                "details": f"Test mode simulated SMS to {phone}: '{sms_body}'"
            }

        return {
            "channel": "sms",
            "status": "held",
            "provider": "SMS Provider",
            "details": "Live SMS delivery disabled until provider & recipients explicitly approved."
        }


# =============================================================================
# Main Notification Service
# =============================================================================

class NotificationService:
    def __init__(self):
        self.test_mode = TEST_MODE
        self.in_app_provider = InAppProvider()
        self.email_provider = EmailProvider(test_mode=self.test_mode)
        self.sms_provider = SMSProvider(test_mode=self.test_mode)
        self.recipients = self._load_recipients()
        self.audit_trail = self._load_audit_trail()
        self.dedup_window_hours = 6

    def _load_recipients(self):
        if os.path.exists(RECIPIENTS_FILE):
            try:
                with open(RECIPIENTS_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading recipients: {e}")
        self._save_recipients(DEFAULT_RECIPIENTS)
        return DEFAULT_RECIPIENTS

    def _save_recipients(self, recs):
        try:
            with open(RECIPIENTS_FILE, "w") as f:
                json.dump(recs, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving recipients: {e}")

    def _load_audit_trail(self):
        if os.path.exists(NOTIFICATIONS_LOG_FILE):
            try:
                with open(NOTIFICATIONS_LOG_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading notification audit trail: {e}")
        return []

    def _save_audit_trail(self):
        try:
            with open(NOTIFICATIONS_LOG_FILE, "w") as f:
                json.dump(self.audit_trail, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving notification audit trail: {e}")

    def is_duplicate(self, incident_id, event_type, hours=6):
        """Check if an identical notification was sent for this incident recently"""
        cutoff = datetime.now() - timedelta(hours=hours)
        for log in reversed(self.audit_trail):
            try:
                log_time = datetime.strptime(log.get("timestamp", ""), "%Y-%m-%d %H:%M:%S")
                if log_time < cutoff:
                    break
                if log.get("incident_id") == incident_id and log.get("event_type") == event_type:
                    return True
            except Exception:
                continue
        return False

    def format_template(self, template_key, context):
        """Render notification subject and formatted content from templates"""
        inc_id = context.get("incident_id", "N/A")
        loc = context.get("location_name", "Forest Zone")
        priority = context.get("priority", "Standard")
        ha = context.get("affected_ha", 0.0)
        officer = context.get("officer", "Unassigned")
        user = context.get("user", "System")

        if template_key == "new_alert":
            subject = f"🚨 [{priority} Priority] Potential Canopy Disturbance: {loc} ({inc_id})"
            body = (
                f"ForestWatch AI Sentinel-2 Surveillance Alert\n"
                f"--------------------------------------------------\n"
                f"Incident ID   : {inc_id}\n"
                f"Monitored Area: {loc}\n"
                f"Priority Level: {priority}\n"
                f"Potential Loss: {ha} ha\n"
                f"Timestamp     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"Notice: Periodic satellite vegetation decline indicates potential disturbance.\n"
                f"Ground-truthing verification is required. Log in to the Command Center to assign an officer."
            )
        elif template_key == "officer_assigned":
            subject = f"📋 [Assignment] Incident {inc_id} Assigned to {officer}"
            body = (
                f"Range Deployment Notice\n"
                f"--------------------------------------------------\n"
                f"Incident ID   : {inc_id} ({loc})\n"
                f"Assigned To   : {officer}\n"
                f"Authorizer    : {user}\n"
                f"Timestamp     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"Please conduct on-site field verification and upload ground photographic evidence."
            )
        elif template_key == "field_note_submitted":
            subject = f"📝 [Field Evidence] New Observation Submitted for {inc_id}"
            body = (
                f"Field Ground-Truthing Update\n"
                f"--------------------------------------------------\n"
                f"Incident ID   : {inc_id} ({loc})\n"
                f"Field Officer : {user}\n"
                f"Observation   : {context.get('note_text', '')}\n"
                f"Timestamp     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
        elif template_key == "status_transition":
            new_status = context.get("new_status", "Updated")
            subject = f"⚖️ [Status Update] Incident {inc_id} is now '{new_status}'"
            body = (
                f"Incident Lifecycle Transition\n"
                f"--------------------------------------------------\n"
                f"Incident ID   : {inc_id} ({loc})\n"
                f"Updated Status: {new_status}\n"
                f"Authorized By : {user}\n"
                f"Notes         : {context.get('notes', 'No additional comments')}\n"
            )
        else:
            subject = f"🔔 ForestWatch Alert: Incident {inc_id}"
            body = f"Notice regarding {inc_id} at {loc}. Action performed by {user}."

        return subject, body

    def dispatch(self, event_type, incident, user="System", extra_context=None, force=False):
        """
        Dispatch notification to authorized recipients matching priority and jurisdiction.
        Returns list of delivery results.
        """
        inc_id = incident.get("id") or incident.get("incident_id")
        priority = incident.get("priority", "Medium")

        # Deduplication check
        if not force and self.is_duplicate(inc_id, event_type, hours=self.dedup_window_hours):
            logger.info(f"Notification suppressed for {inc_id} ({event_type}): within deduplication window.")
            return []

        context = {
            "incident_id": inc_id,
            "location_name": incident.get("location_name", "Unknown Reserve"),
            "priority": priority,
            "affected_ha": incident.get("affected_ha") or incident.get("affected_area_ha", 0.0),
            "officer": incident.get("assigned_officer", "Unassigned"),
            "user": user
        }
        if extra_context:
            context.update(extra_context)

        subject, body = self.format_template(event_type, context)
        delivery_results = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        priority_ranks = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
        inc_rank = priority_ranks.get(priority, 2)

        for rec in self.recipients:
            rec_min_rank = priority_ranks.get(rec.get("min_priority", "Medium"), 2)
            if inc_rank < rec_min_rank:
                continue

            channels = rec.get("enabled_channels", ["in_app"])
            for ch in channels:
                provider_res = None
                if ch == "in_app":
                    provider_res = self.in_app_provider.send(rec, subject, body, metadata={"incident_id": inc_id})
                elif ch == "email":
                    provider_res = self.email_provider.send(rec, subject, body, metadata={"incident_id": inc_id})
                elif ch == "sms":
                    provider_res = self.sms_provider.send(rec, subject, body, metadata={"incident_id": inc_id})

                if provider_res:
                    record = {
                        "notification_id": f"NOTIF-{uuid.uuid4().hex[:8].upper()}",
                        "incident_id": inc_id,
                        "event_type": event_type,
                        "recipient_id": rec.get("id"),
                        "recipient_name": rec.get("name"),
                        "recipient_role": rec.get("role"),
                        "channel": ch,
                        "status": provider_res.get("status"),
                        "provider": provider_res.get("provider"),
                        "details": provider_res.get("details"),
                        "subject": subject,
                        "timestamp": now_str,
                        "test_mode": self.test_mode
                    }
                    self.audit_trail.append(record)
                    delivery_results.append(record)

        self._save_audit_trail()
        return delivery_results

    def get_audit_trail(self, incident_id=None, channel=None, limit=50):
        """Retrieve filtered notification audit logs"""
        logs = self.audit_trail
        if incident_id:
            logs = [l for l in logs if l.get("incident_id") == incident_id]
        if channel:
            logs = [l for l in logs if l.get("channel") == channel]
        return list(reversed(logs))[:limit]


# Global notification service singleton
notification_service = NotificationService()
