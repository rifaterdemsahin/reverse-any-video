"""Admin area: the analyzer, the operator pages, outputs and the sanity check. Admin sign-in only.

Routes are registered on the app in server.py. Shared state and helpers live there too.
"""
import json
import os
import re
from pathlib import Path

from fastapi import Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

import accounts
import admin
import deepinfra
import gmail
import payments
import pricing
import storage
from server import ACCESS_TOKEN, DOCS, OUTPUT_FILES, app, get_store

# --------------------------------------------------------------------------- #
# Admin area: the analyzer and operator pages, for one Azure account only      #
# --------------------------------------------------------------------------- #

def _admin_page(request: Request, name: str):
    if admin.email_from_session(request.cookies.get(admin.ADMIN_COOKIE)):
        return FileResponse(DOCS / name, media_type="text/html")
    if not admin.configured():
        return HTMLResponse("Admin sign-in is not set up yet on this server.", status_code=503)
    return RedirectResponse("/admin/login", status_code=303)


@app.get("/admin")
def admin_analyzer(request: Request):
    return _admin_page(request, "index.html")


def _admin_only(request: Request):
    if not admin.email_from_session(request.cookies.get(admin.ADMIN_COOKIE)):
        raise HTTPException(401, "Sign in as the admin first.")


@app.get("/admin/api/outputs")
def admin_outputs(request: Request):
    _admin_only(request)
    if not storage.configured():
        raise HTTPException(503, "Azure storage is not configured.")
    return {"jobs": get_store().list_job_outputs()}


@app.get("/admin/api/outputs/{job_id}/{name}")
def admin_output_file(request: Request, job_id: str, name: str):
    _admin_only(request)
    if name not in OUTPUT_FILES or not re.fullmatch(r"[0-9a-f]{12}", job_id):
        raise HTTPException(404, "Not found.")
    data = get_store().read_job_output(job_id, name)
    if data is None:
        raise HTTPException(404, "Not found.")
    return Response(data, media_type=OUTPUT_FILES[name],
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/admin/outputs")
def admin_outputs_page(request: Request):
    return _admin_page(request, "admin-outputs.html")


@app.get("/admin/guide")
def admin_guide(request: Request):
    return _admin_page(request, "admin-guide.html")


@app.get("/admin/api/sanity")
def admin_sanity(request: Request):
    """Each check runs for real. The page at /admin/sanity shows the results. Admin only."""
    if not admin.email_from_session(request.cookies.get(admin.ADMIN_COOKIE)):
        raise HTTPException(401, "Sign in as the admin first.")
    checks = []

    def check(name: str, fn, fix: str):
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001 - a failing check is a result, not a crash
            ok, detail = False, f"{type(e).__name__}: {e}"
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fix": "" if ok else fix})

    check("Server is running and imports every module",
          lambda: (True, f"{len(OUTPUT_FILES)} output files defined"), "Check fly logs for an import error.")
    check("Access token is set (auth required)",
          lambda: (ACCESS_TOKEN is not None, "set" if ACCESS_TOKEN else "not set"),
          "fly secrets set --app reverse-any-video ACCESS_TOKEN=<token>")
    check("Azure storage reachable (projects and internal files)",
          lambda: (get_store() is not None, "container reachable"),
          "Set AZURE_KEYVAULT_URL and the service principal secrets, then fly deploy.")
    check("DeepInfra key set (storyboard and EDL clip names)",
          lambda: (deepinfra.api_key() is not None, "set" if deepinfra.api_key() else "not set"),
          "fly secrets set --stage DEEPINFRA_API_KEY=<key>, then fly deploy.")
    check("Sign-in email (Gmail) configured",
          lambda: (gmail.configured(), "configured" if gmail.configured() else "missing"),
          "Put GMAIL-OAUTH-CLIENT-ID, GMAIL-OAUTH-CLIENT-SECRET and GMAIL-OAUTH-REFRESH-TOKEN in Key Vault.")
    check("Session secret set (customer and admin sessions)",
          lambda: (accounts._secret() is not None, "set"),
          "fly secrets set --stage SESSION_SECRET=$(openssl rand -hex 32), then fly deploy.")
    check("Admin sign-in configured",
          lambda: (admin.configured(), "configured" if admin.configured() else "missing"),
          "Create the admin app and its secret (see the admin guide, step 9).")
    check("Stripe test key set",
          lambda: (payments.configured(), "set" if payments.configured() else "not set"),
          "fly secrets set --stage STRIPE_SECRET_KEY=sk_test_...")
    check("Stripe webhook secret set",
          lambda: (payments.webhook_secret() is not None, "set" if payments.webhook_secret() else "not set"),
          "fly secrets set --stage STRIPE_WEBHOOK_SECRET=whsec_...")
    check("Pricing: quote and packs for a 5-minute video",
          lambda: (_pricing_ok(), "price positive, three packs"),
          "Check pricing.py and the PACKAGE_AMOUNTS list.")
    check("Customer bundle includes README.md and AGENTS.md",
          lambda: ("README.md" in OUTPUT_FILES and "AGENTS.md" in OUTPUT_FILES, "both listed"),
          "Add them to OUTPUT_FILES in server.py.")
    check("No internal file is in the customer bundle",
          lambda: (not ({"frames.zip", "analysis.json", "video.mp4", "llm_trace.json", "progress.json"} & set(OUTPUT_FILES)),
                   "none listed"),
          "Remove the internal file from OUTPUT_FILES.")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def _pricing_ok() -> bool:
    q = pricing.quote(pricing.estimate(300))
    packs = pricing.package_estimates(300)
    return q["price"] > 0 and len(packs) == 3


@app.get("/admin/sanity")
def admin_sanity_page(request: Request):
    return _admin_page(request, "admin-sanity.html")


@app.get("/admin/setup")
def admin_setup(request: Request):
    return _admin_page(request, "setup.html")


@app.get("/admin/settings")
def admin_settings(request: Request):
    return _admin_page(request, "settings.html")


@app.get("/admin/login")
def admin_login():
    if not admin.configured():
        return HTMLResponse("Admin sign-in is not set up yet on this server.", status_code=503)
    state, nonce = admin.new_state()
    return RedirectResponse(admin.authorize_url(f"{PUBLIC_URL}/admin/callback", state, nonce), status_code=303)


@app.get("/admin/callback")
def admin_callback(code: str = "", state: str = "", error: str = ""):
    if error:
        return HTMLResponse("Sign-in was cancelled or refused.", status_code=403)
    try:
        nonce = admin.check_state(state)
        claims = admin.exchange_code(code, f"{PUBLIC_URL}/admin/callback")
        email = admin.admin_email(claims, nonce)
    except admin.AdminError as e:
        return HTMLResponse(f"Not allowed: {e}", status_code=403)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(admin.ADMIN_COOKIE, admin.session_value(email), max_age=admin.SESSION_TTL,
                    httponly=True, secure=True, samesite="lax")
    return resp


@app.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(admin.ADMIN_COOKIE)
    return resp


