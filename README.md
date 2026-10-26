# Agent Studio

A small, working AI workflow builder: draw a workflow on a React Flow canvas,
save it, and run it on a LangGraph engine.

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17, LangGraph
- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS 4, React Flow 12

## Run it

```bash
docker compose up -d                       # PostgreSQL on 127.0.0.1:55433

cd backend
uv sync
uv run alembic upgrade head                # create the tables
uv run python -m studio.seed               # demo users (password: studio-demo)
uv run uvicorn studio.main:app --port 8000

cd ../frontend
npm install
npm run dev                                # http://localhost:3000
```

Demo users in **Acme AI**: `alice@acme.test` (organization admin, owner of
Support Bot), `bob@acme.test` (editor), `carol@acme.test` (viewer) and
`erin@acme.test` (in no project yet). `dave@globex.test` is in **Globex**, a
separate tenant.

## Test it

```bash
cd backend && uv run pytest                # needs the PostgreSQL above
cd frontend && npx tsc --noEmit && npm run lint
```

The tests create a throwaway database, run the migrations, and empty the
tables before every test.

## How it fits together

- The browser only talks to `http://localhost:3000`. Next.js proxies `/api/*`
  to FastAPI, so the session cookie is first-party and no CORS is needed.
- Sign-in sets an `HttpOnly`, `SameSite=Lax` session cookie; only a SHA-256
  hash of the token is stored. Every write must carry `X-Requested-With: studio`,
  which a cross-site page cannot send (CSRF protection).
- Every query is scoped to the user's organization (tenant).
- A workflow is React Flow JSON (`nodes`, `edges`). Running it compiles the graph
  into a LangGraph `StateGraph` and runs it in the background; the run can be
  cancelled between steps.
- Every save names the revision it started from. A save based on an older
  revision is rejected with `409` and nothing is overwritten. Every revision is
  kept; restoring an old one saves it again as a new revision.
- The append-only `audit_events` table records sign-ins, changes, rejected saves
  and runs, with a request id that matches the response's `X-Request-ID`.
  Organization admins read it at `/audit` and can export CSV. In production, run
  the app as a database role that does not own `audit_events`, so the
  append-only trigger can't be switched off from the app.
- Project access comes only from `project_members` (owner, admin, editor,
  viewer). The rules live in `studio/permissions.py`; non-members get `404`,
  members whose role is too low get `403` and a `permission.denied` audit event.
  New members join through single-use invitation links that expire after 7 days.
- Sign-in and invitations are rate limited in memory, per process. Use a shared
  store (Redis) behind `studio/ratelimit.py` before running several workers.
- OAuth connections (`studio/routes/connections.py`) use the authorization code
  flow with PKCE and a fixed redirect URI. Tokens are encrypted with
  `TOKEN_ENCRYPTION_KEYS` (Fernet, rotatable) and never leave the backend.
  Disconnecting revokes the token at the provider. For local work without a
  GitHub OAuth app, run the test provider in `backend/devtools/` (see
  `.env.example`). Workflows refuse to store anything that looks like a credential.
- The editor opens a WebSocket at `/api/workflows/{id}/live` (proxied by
  Next.js like the rest of `/api`). It shows who else has the workflow open and
  who has unsaved changes, and announces saves as soon as they are committed.
  The server checks the `Origin` header, the session and project membership,
  and keeps checking membership while the socket is open. The hub
  (`studio/live.py`) lives in one process's memory: add a broker such as Redis
  pub/sub before running several workers.
