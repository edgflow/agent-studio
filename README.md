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

Demo users: `alice@acme.test` (organization admin), `bob@acme.test` and
`carol@acme.test` in **Acme AI**; `dave@globex.test` in **Globex**, a separate tenant.

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
