"""
Microsoft 365 (Entra) sign-in via MSAL, delegated auth-code flow.
When Entra creds are absent (config.AUTH_ENABLED False) the app runs in DEV mode:
a synthetic user whose role can be switched with /setrole/<role> for previewing.
"""
import functools
from flask import session, redirect, request, url_for
import config

try:
    import msal
except Exception:
    msal = None


def _initials(name):
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "U"
    return (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")).upper()


def _cca():
    if not (msal and config.AUTH_ENABLED):
        return None
    return msal.ConfidentialClientApplication(
        config.MS_CLIENT_ID, authority=config.MS_AUTHORITY,
        client_credential=config.MS_CLIENT_SECRET)


def _redirect_uri():
    return config.PUBLIC_BASE_URL + config.MS_REDIRECT_PATH


def role_from_claims(claims):
    for r in (claims.get("roles") or []):
        if r in config.ROLE_CLAIM_MAP:
            return config.ROLE_CLAIM_MAP[r]
    return config.DEFAULT_ROLE


def current_user():
    u = session.get("user")
    if u:
        return u
    if not config.AUTH_ENABLED:                       # DEV fallback
        role = (session.get("dev_role") or config.DEV_ROLE).lower()
        if role not in (config.ROLE_MANAGER, config.ROLE_FSE, config.ROLE_EMPLOYEE):
            role = config.DEFAULT_ROLE
        return {"name": "Demo User", "email": config.NOTIFY_EMAIL, "initials": "DU",
                "role": role, "manager_email": config.NOTIFY_EMAIL, "dev": True}
    return None


def login_required(f):
    @functools.wraps(f)
    def wrap(*a, **k):
        if current_user():
            return f(*a, **k)
        return redirect(url_for("login", next=request.path))
    return wrap


def login():
    if not config.AUTH_ENABLED:
        return redirect(request.args.get("next") or "/")
    flow = _cca().initiate_auth_code_flow(config.MS_SCOPES, redirect_uri=_redirect_uri())
    session["flow"] = flow
    session["next"] = request.args.get("next") or "/"
    return redirect(flow["auth_uri"])


def callback():
    if not config.AUTH_ENABLED:
        return redirect("/")
    try:
        result = _cca().acquire_token_by_auth_code_flow(session.get("flow", {}), request.args)
    except Exception as e:
        return "Sign-in error: %s" % e, 400
    if "error" in result:
        return "Sign-in failed: %s" % result.get("error_description", result["error"]), 400
    claims = result.get("id_token_claims", {})
    email = claims.get("preferred_username") or claims.get("email") or ""
    name = claims.get("name") or email or "MMS User"
    user = {"name": name, "email": email, "initials": _initials(name),
            "role": role_from_claims(claims), "manager_email": "", "oid": claims.get("oid", "")}
    try:
        import graph
        mgr = graph.get_manager_email(email or claims.get("oid"))
        if mgr:
            user["manager_email"] = mgr
    except Exception:
        pass
    session["user"] = user
    return redirect(session.pop("next", "/"))


def logout():
    session.clear()
    if config.AUTH_ENABLED:
        return redirect(config.MS_AUTHORITY +
                        "/oauth2/v2.0/logout?post_logout_redirect_uri=" + config.PUBLIC_BASE_URL)
    return redirect("/")
