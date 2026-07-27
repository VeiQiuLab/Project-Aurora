"""Remote API security policy foundation.

This module defines static API policy metadata and policy checks for future
Remote API enforcement. It does not change current API behavior.
"""

from modules.access_control import ACCESS_ALLOWED, ACCESS_DENIED, ACCESS_PENDING, access_decision


API_PUBLIC = "Public"
API_PROTECTED = "Protected"
API_ADMIN = "Admin"

RISK_LOW = "Low"
RISK_MEDIUM = "Medium"
RISK_HIGH = "High"


DEFAULT_POLICY = {
    "endpoint": "",
    "category": API_PROTECTED,
    "required_auth": True,
    "required_device": True,
    "required_pairing": True,
    "risk_level": RISK_MEDIUM,
}


API_POLICIES = {
    "/": {
        "category": API_PUBLIC,
        "required_auth": False,
        "required_device": False,
        "required_pairing": False,
        "risk_level": RISK_LOW,
    },
    "/status": {
        "category": API_PUBLIC,
        "required_auth": False,
        "required_device": False,
        "required_pairing": False,
        "risk_level": RISK_LOW,
    },
    "/chat": {
        "category": API_PUBLIC,
        "required_auth": False,
        "required_device": False,
        "required_pairing": False,
        "risk_level": RISK_LOW,
    },
    "/api/mobile-status": {
        "category": API_PUBLIC,
        "required_auth": False,
        "required_device": False,
        "required_pairing": False,
        "risk_level": RISK_LOW,
    },
    "/api/mobile-chat": {
        "category": API_PROTECTED,
        "required_auth": True,
        "required_device": True,
        "required_pairing": True,
        "risk_level": RISK_MEDIUM,
    },
    "/api/mobile-conversations": {
        "category": API_PROTECTED,
        "required_auth": True,
        "required_device": True,
        "required_pairing": True,
        "risk_level": RISK_MEDIUM,
    },
    "/api/mobile-conversation": {
        "category": API_PROTECTED,
        "required_auth": True,
        "required_device": True,
        "required_pairing": True,
        "risk_level": RISK_MEDIUM,
    },
    "/api/mobile-conversation/new": {
        "category": API_PROTECTED,
        "required_auth": True,
        "required_device": True,
        "required_pairing": True,
        "risk_level": RISK_MEDIUM,
    },
    "/api/remote": {
        "category": API_ADMIN,
        "required_auth": True,
        "required_device": True,
        "required_pairing": True,
        "risk_level": RISK_HIGH,
    },
}


def normalize_endpoint(endpoint):
    route = str(endpoint or "").split("?", 1)[0].rstrip("/")
    if not route:
        return "/"
    return route


def make_policy(endpoint, overrides=None):
    policy = dict(DEFAULT_POLICY)
    policy["endpoint"] = normalize_endpoint(endpoint)
    if isinstance(overrides, dict):
        policy.update(overrides)
    return policy


def get_policy(endpoint):
    route = normalize_endpoint(endpoint)
    if route.startswith("/api/remote/"):
        return make_policy(route, API_POLICIES["/api/remote"])
    return make_policy(route, API_POLICIES.get(route, {}))


def check_policy(endpoint, context=None):
    """Check a policy against an access/auth context without enforcing APIs."""

    policy = get_policy(endpoint)
    context = context if isinstance(context, dict) else {}
    auth = context.get("auth", {})

    authenticated = bool(context.get("authenticated", False) or auth.get("authenticated", False))
    device_id = str(context.get("device_id", "") or "")
    pairing_verified = bool(context.get("pairing_verified", False) or context.get("pairing_status") == "Verified")

    if policy.get("required_auth") and not authenticated:
        return _policy_result(policy, ACCESS_PENDING, "Authentication required.")
    if policy.get("required_device") and not device_id:
        return _policy_result(policy, ACCESS_PENDING, "Device identity required.")
    if policy.get("required_pairing") and not pairing_verified:
        return _policy_result(policy, ACCESS_PENDING, "Verified pairing required.")
    return _policy_result(policy, ACCESS_ALLOWED, "Policy check passed.")


def _policy_result(policy, result, reason):
    decision = access_decision(
        result=result if result in {ACCESS_ALLOWED, ACCESS_DENIED, ACCESS_PENDING} else ACCESS_PENDING,
        reason=reason,
        device_id="",
        api_name=policy.get("endpoint", ""),
    )
    decision["policy"] = dict(policy)
    decision["category"] = policy.get("category", API_PROTECTED)
    decision["risk_level"] = policy.get("risk_level", RISK_MEDIUM)
    return decision
