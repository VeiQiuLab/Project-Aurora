"""Authentication middleware foundation for Aurora HTTP APIs.

This module does not generate or validate real device tokens yet. It provides
one shared decision layer that future LAN and Remote APIs can call before
serving protected requests.
"""

from functools import wraps


REMOTE_MODE_DISABLED = "Disabled"
REMOTE_MODE_LAN_ONLY = "LAN Only"
REMOTE_MODE_PAIRED_LAN = "Paired LAN"
REMOTE_MODE_SECURE_REMOTE_READY = "Secure Remote Ready"


PROTECTED_SCOPES = {
    "/api/mobile-chat": "mobile.chat",
    "/api/mobile-conversations": "mobile.conversations",
    "/api/mobile-conversation": "mobile.conversation",
    "/api/mobile-conversation/new": "mobile.conversation.new",
    "/api/remote": "remote"
}


def normalize_remote_mode(config):
    if not isinstance(config, dict):
        config = {}
    if not bool(config.get("enabled", False)):
        return REMOTE_MODE_DISABLED

    mode = str(config.get("mode") or "local").strip().casefold().replace("-", "_")
    if mode in {"paired", "paired_lan", "device_pairing"}:
        return REMOTE_MODE_PAIRED_LAN
    if mode in {"secure", "secure_remote", "secure_remote_ready"}:
        return REMOTE_MODE_SECURE_REMOTE_READY
    return REMOTE_MODE_LAN_ONLY


def protected_scope(path):
    route = str(path or "").split("?", 1)[0].rstrip("/")
    if route in PROTECTED_SCOPES:
        return PROTECTED_SCOPES[route]
    if route.startswith("/api/remote/"):
        return PROTECTED_SCOPES["/api/remote"]
    return ""


def _load_remote_config(remote_manager=None):
    if remote_manager is None:
        try:
            from modules.remote import RemoteAccessManager

            remote_manager = RemoteAccessManager()
        except Exception:
            return {}
    try:
        return remote_manager.load()
    except Exception:
        return {}


def _load_auth_status(authentication_manager=None, remote_manager=None):
    if authentication_manager is None:
        try:
            from modules.authentication import AuthenticationManager

            file_path = getattr(remote_manager, "file_path", None)
            authentication_manager = AuthenticationManager(file_path)
        except Exception:
            return {}
    try:
        return authentication_manager.status()
    except Exception:
        return {}


def _header_value(headers, name):
    if headers is None:
        return ""
    try:
        return str(headers.get(name, "") or "").strip()
    except AttributeError:
        if isinstance(headers, dict):
            return str(headers.get(name, "") or headers.get(name.lower(), "") or "").strip()
        return ""


def extract_bearer_token(headers):
    authorization = _header_value(headers, "Authorization")
    if not authorization:
        return ""
    prefix = "bearer "
    if authorization.casefold().startswith(prefix):
        return authorization[len(prefix):].strip()
    return ""


def authenticate_request(
    request=None,
    headers=None,
    path="",
    method="",
    remote_manager=None,
    authentication_manager=None,
    enforce=False
):
    """Return an authentication decision for a future protected API request.

    `enforce=False` keeps current LAN Mobile behavior unchanged while still
    exposing the same decision payload future enforcement will use.
    """

    if request is not None:
        headers = headers if headers is not None else getattr(request, "headers", None)
        path = path or getattr(request, "path", "")
        method = method or getattr(request, "command", "")

    config = _load_remote_config(remote_manager)
    auth_status = _load_auth_status(authentication_manager, remote_manager)
    mode = normalize_remote_mode(config)
    scope = protected_scope(path)
    token = extract_bearer_token(headers)

    token_required = mode in {REMOTE_MODE_PAIRED_LAN, REMOTE_MODE_SECURE_REMOTE_READY}
    configured = bool(auth_status.get("configured", False))
    token_configured = bool(auth_status.get("token_configured", False))
    storage_ready = bool(auth_status.get("secure_storage_available", False) or auth_status.get("secure_storage_configured", False))
    has_token = bool(token)

    allowed = True
    reason = "Allowed by compatibility policy."
    authenticated = False

    if mode == REMOTE_MODE_DISABLED:
        allowed = not enforce
        reason = "Remote is disabled."
    elif mode == REMOTE_MODE_LAN_ONLY:
        allowed = True
        reason = "LAN Only mode allows compatibility access."
    elif token_required and not configured:
        allowed = False
        reason = "Authentication is not configured."
    elif token_required and not token_configured:
        allowed = False
        reason = "Token authentication is not configured."
    elif token_required and not storage_ready:
        allowed = False
        reason = "Secure credential storage is unavailable."
    elif token_required and not has_token:
        allowed = False
        reason = "Bearer token is missing."
    elif token_required:
        allowed = False
        reason = "Device token validation is not implemented yet."
    else:
        authenticated = bool(configured and has_token)

    if not enforce and not allowed:
        reason = f"{reason} Compatibility mode did not block the request."
        allowed = True

    return {
        "allowed": bool(allowed),
        "denied": not bool(allowed),
        "reason": reason,
        "mode": mode,
        "method": str(method or ""),
        "path": str(path or ""),
        "scope": scope,
        "protected": bool(scope),
        "authenticated": authenticated,
        "token_required": token_required,
        "enforced": bool(enforce)
    }


def check_permission(decision, permission=None):
    if not isinstance(decision, dict):
        return {
            "allowed": False,
            "denied": True,
            "reason": "Authentication decision is invalid.",
            "permission": permission or ""
        }
    if not decision.get("allowed", False):
        result = dict(decision)
        result["permission"] = permission or ""
        return result
    result = dict(decision)
    result["permission"] = permission or ""
    result["reason"] = decision.get("reason") or "Permission allowed."
    return result


def auth_required(permission=None, enforce=False):
    """Decorator form for future API handlers.

    Current LAN handlers call `authenticate_request()` directly so they can
    preserve response format compatibility.
    """

    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            request = args[0] if args else None
            decision = authenticate_request(request=request, enforce=enforce)
            permission_decision = check_permission(decision, permission)
            if permission_decision.get("denied"):
                return {
                    "ok": False,
                    "error": "Authentication Required",
                    "reason": permission_decision.get("reason", "Authentication failed."),
                    "auth": permission_decision
                }
            return function(*args, **kwargs)

        return wrapper

    return decorator
