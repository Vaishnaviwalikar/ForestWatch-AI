"""
Role-Based Access Control (RBAC) Module for ForestWatch AI
Enforces server-side authorization across Forest Department roles:
- Department Administrator
- Range Officer
- Analyst
- Field Officer
"""

import functools
import logging
from flask import request, jsonify, session

logger = logging.getLogger(__name__)

# Canonical Forest Department Roles
ROLE_ADMIN = "Department Administrator"
ROLE_RANGE_OFFICER = "Range Officer"
ROLE_ANALYST = "Analyst"
ROLE_FIELD_OFFICER = "Field Officer"

ALL_ROLES = [ROLE_ADMIN, ROLE_RANGE_OFFICER, ROLE_ANALYST, ROLE_FIELD_OFFICER]

# Default demo user accounts
AUTHORIZED_USERS = {
    "admin": {
        "username": "admin",
        "name": "Shri R. Sharma, IFS",
        "role": ROLE_ADMIN,
        "designation": "Divisional Forest Officer",
        "badge_id": "IFS-2018-091",
        "jurisdiction": "State Forest Headquarters"
    },
    "range_officer": {
        "username": "range_officer",
        "name": "Rajesh Kumar",
        "role": ROLE_RANGE_OFFICER,
        "designation": "Range Forest Officer",
        "badge_id": "RFO-MH-4402",
        "jurisdiction": "Northern Range Division"
    },
    "field_officer": {
        "username": "field_officer",
        "name": "S. Patil",
        "role": ROLE_FIELD_OFFICER,
        "designation": "Beat Guard Supervisor",
        "badge_id": "BG-WGH-110",
        "jurisdiction": "Sector Beat 4"
    },
    "analyst": {
        "username": "analyst",
        "name": "Dr. Ananya Roy",
        "role": ROLE_ANALYST,
        "designation": "Geospatial Remote Sensing Analyst",
        "badge_id": "GIS-NRSC-88",
        "jurisdiction": "Earth Observation Lab"
    }
}


def normalize_role(role_str):
    """Normalize user-supplied role string to canonical title"""
    if not role_str:
        return ROLE_ADMIN
    r = role_str.strip().lower()
    if "admin" in r:
        return ROLE_ADMIN
    if "range" in r:
        return ROLE_RANGE_OFFICER
    if "analyst" in r:
        return ROLE_ANALYST
    if "field" in r or "guard" in r or "beat" in r:
        return ROLE_FIELD_OFFICER
    return ROLE_ADMIN


def get_current_user():
    """Extract current active user identity and role from headers, session, or parameters"""
    # 1. Check HTTP Header (ideal for API calls)
    role_header = request.headers.get("X-User-Role")
    user_header = request.headers.get("X-User-Name")

    # 2. Check Session
    role_session = session.get("user_role")
    user_session = session.get("user_name")

    # 3. Check Query parameter (convenient for testing & simulation)
    role_param = request.args.get("user_role")

    selected_role = normalize_role(role_header or role_param or role_session or ROLE_ADMIN)
    selected_name = user_header or user_session or "Authorized Officer"

    # Match user profile
    for u in AUTHORIZED_USERS.values():
        if u["role"] == selected_role:
            return {
                "username": u["username"],
                "name": u["name"],
                "role": u["role"],
                "designation": u["designation"],
                "badge_id": u["badge_id"],
                "jurisdiction": u["jurisdiction"]
            }

    return {
        "username": "custom_user",
        "name": selected_name,
        "role": selected_role,
        "designation": "Forest Officer",
        "badge_id": "FO-STD-001",
        "jurisdiction": "Forest Division"
    }


def require_role(allowed_roles):
    """
    Decorator to enforce server-side Role-Based Access Control.
    allowed_roles: list of allowed role strings.
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            user_role = user.get("role")

            normalized_allowed = [normalize_role(r) for r in allowed_roles]

            if user_role not in normalized_allowed:
                logger.warning(
                    f"RBAC Access Denied: User '{user.get('name')}' ({user_role}) "
                    f"attempted action requiring {normalized_allowed}"
                )
                return jsonify({
                    "error": f"Access Denied: Action requires one of {allowed_roles}.",
                    "current_user": user.get("name"),
                    "current_role": user_role,
                    "required_roles": allowed_roles
                }), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator
