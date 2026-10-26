"""A small OAuth 2.0 provider for development, demos and tests.

It copies the shape of a GitHub OAuth app: /authorize with PKCE (S256 only),
/token, GET /user, and DELETE /applications/{client_id}/token. It checks
everything a real provider checks (client, redirect URI, single-use codes,
PKCE), and keeps everything in memory. Never expose it beyond your machine.

    DEV_OAUTH_CLIENT_SECRET=... uv run uvicorn devtools.oauth_provider:app --port 8010
"""

import base64
import hashlib
import html
import os
import secrets
import time
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

CLIENT_ID = os.environ.get("DEV_OAUTH_CLIENT_ID", "agent-studio-dev")
CLIENT_SECRET = os.environ.get("DEV_OAUTH_CLIENT_SECRET", "dev-only-secret")
REDIRECT_URIS = os.environ.get(
    "DEV_OAUTH_REDIRECT_URIS", "http://localhost:3000/api/connections/local/callback"
).split(",")
ACCOUNT = {"id": 4242, "login": "dev-octocat"}
SCOPES = {"read:user"}

codes: dict[str, dict] = {}  # authorization code -> what it was issued for
tokens: dict[str, set[str]] = {}  # access token -> granted scopes

app = FastAPI(title="Local OAuth provider")

PAGE = """<!doctype html><meta charset="utf-8"><title>Local OAuth provider</title>
<style>body{{font:16px system-ui;background:#0d1117;color:#e6edf3;display:grid;place-items:center;
height:100vh;margin:0}}form{{background:#161b22;border:1px solid #30363d;border-radius:12px;
padding:28px;width:380px}}button{{font:inherit;padding:8px 18px;border-radius:6px;border:0;
margin-right:8px;cursor:pointer}}.ok{{background:#238636;color:#fff}}code{{color:#79c0ff}}</style>
<form method="post" action="/authorize">
<p style="color:#8b949e;margin-top:0">Local test provider &middot; signed in as
<b>{login}</b></p>
<h2 style="margin:8px 0 16px">Authorize Agent Studio?</h2>
<p>It asks for: <code>{scope}</code></p>
{fields}
<p><button class="ok" name="decision" value="allow">Authorize</button>
<button name="decision" value="deny">Cancel</button></p></form>"""


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def form(request: Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}


@app.get("/authorize")
def authorize(request: Request) -> Response:
    q = dict(request.query_params)
    # Never redirect to a URI that wasn't registered: show an error page instead.
    if q.get("client_id") != CLIENT_ID or q.get("redirect_uri") not in REDIRECT_URIS:
        return HTMLResponse("Unknown client or redirect URI.", status_code=400)
    if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256":
        return HTMLResponse("Only the authorization code flow with PKCE (S256).", 400)
    if not q.get("code_challenge") or not q.get("state"):
        return HTMLResponse("Missing code_challenge or state.", status_code=400)
    keep = ("redirect_uri", "state", "code_challenge", "scope")
    fields = "".join(
        f'<input type="hidden" name="{k}" value="{html.escape(q.get(k, ""))}">' for k in keep
    )
    page = PAGE.format(login=ACCOUNT["login"], scope=html.escape(q.get("scope", "")), fields=fields)
    return HTMLResponse(page)


@app.post("/authorize")
async def decide(request: Request) -> Response:
    f = await form(request)
    if f.get("redirect_uri") not in REDIRECT_URIS:
        return HTMLResponse("Unknown redirect URI.", status_code=400)
    if f.get("decision") != "allow":
        query = urlencode({"error": "access_denied", "state": f.get("state", "")})
        return RedirectResponse(f"{f['redirect_uri']}?{query}", status_code=302)
    code = secrets.token_urlsafe(24)
    codes[code] = {
        "challenge": f.get("code_challenge", ""),
        "redirect_uri": f["redirect_uri"],
        "scopes": set(f.get("scope", "").split()) & SCOPES,
        "expires": time.monotonic() + 60,
    }
    query = urlencode({"code": code, "state": f.get("state", "")})
    return RedirectResponse(f"{f['redirect_uri']}?{query}", status_code=302)


@app.post("/token")
async def token(request: Request) -> JSONResponse:
    f = await form(request)
    issued = codes.pop(f.get("code", ""), None)  # a code works once
    # Like GitHub: problems come back as 200 with an "error" field.
    if f.get("client_id") != CLIENT_ID or f.get("client_secret") != CLIENT_SECRET:
        return JSONResponse({"error": "incorrect_client_credentials"})
    if issued is None or issued["expires"] < time.monotonic():
        return JSONResponse({"error": "bad_verification_code"})
    if f.get("redirect_uri") != issued["redirect_uri"]:
        return JSONResponse({"error": "redirect_uri_mismatch"})
    if s256(f.get("code_verifier", "")) != issued["challenge"]:
        return JSONResponse({"error": "invalid_grant", "error_description": "PKCE check failed"})
    access_token = "dev_" + secrets.token_urlsafe(30)
    tokens[access_token] = issued["scopes"]
    scope = ",".join(sorted(issued["scopes"]))
    return JSONResponse({"access_token": access_token, "token_type": "bearer", "scope": scope})


@app.get("/user")
def user(request: Request) -> JSONResponse:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or auth.removeprefix("Bearer ") not in tokens:
        return JSONResponse({"message": "Bad credentials"}, status_code=401)
    return JSONResponse(ACCOUNT)


@app.delete("/applications/{client_id}/token")
async def revoke(client_id: str, request: Request) -> Response:
    expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    if client_id != CLIENT_ID or request.headers.get("authorization") != f"Basic {expected}":
        return JSONResponse({"message": "Requires authentication"}, status_code=401)
    access_token = (await request.json()).get("access_token", "")
    return Response(status_code=204 if tokens.pop(access_token, None) is not None else 404)
