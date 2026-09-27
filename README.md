# Geobelic

Web app for the Deeptech GigaHack 2026 vineyard field challenge: a React map in `frontend` and a FastAPI API in `backend`. The annotation and route pipeline lives in `ai` and is documented there.

## Start with Docker

You need Docker, and a `backend/.env` the API can read. Compose does not start PostgreSQL.

```bash
cp backend/.env.example backend/.env
# Edit backend/.env: set DATABASE_URL and JWT_SECRET (see below).
docker compose up --build
```

- App: http://localhost:5173
- API: http://localhost:8000
- Interactive API docs: http://localhost:8000/docs

`DATABASE_URL` is used from inside the backend container. `localhost` in that URL is the container, not your machine. Point it at a reachable PostGIS database (for example the Supabase session pooler in `backend/.env.example`). If Postgres runs on the host, use `host.docker.internal` instead of `localhost`.

The frontend image bakes in the API URL at build time. The default is `http://localhost:8000`. Override it when the browser should call a different host:

```bash
VITE_API_BASE_URL=http://localhost:8000 docker compose up --build
```

## Start locally

Use this when you want hot reload. The API and the Vite dev server run on the host, so `DATABASE_URL=postgresql://localhost:5432/gigahack` works if PostGIS is listening there.

### Backend

Python 3.14 matches the API image. PostgreSQL needs the PostGIS extension.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Set DATABASE_URL and JWT_SECRET in .env.
uvicorn app.main:app --reload
```

The API listens on http://localhost:8000. On the first request that needs the database it creates the PostGIS extension and any missing tables. To do that up front:

```bash
python -m app.db
```

A local database, if you do not already have one:

```bash
brew install postgresql@18 postgis
brew services start postgresql@18
createdb gigahack
```

Set `JWT_SECRET` in `.env`, or every restart signs a new secret and logs everyone out:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Frontend

Node 22 matches the frontend image.

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. The dev server calls `http://localhost:8000` unless you set `VITE_API_BASE_URL`.

## Configuration

Copy `backend/.env.example` to `backend/.env`. Real environment variables override the file. Do not commit `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://localhost:5432/gigahack` | PostgreSQL with PostGIS. A Supabase URL must use the session pooler and `sslmode=require`. |
| `JWT_SECRET` | random per process | Signs login tokens. |
| `JWT_TTL_HOURS` | `24` | Token lifetime. |
| `UPLOAD_DIR` | `../uploads` next to the backend | Uploaded rasters. Compose sets this to `/uploads`. |
| `CORS_ORIGINS` | Vite dev and preview origins | Comma-separated allowed origins. Compose allows `http://localhost:5173`. |
| `VITE_API_BASE_URL` | `http://localhost:8000` | API origin baked into the frontend bundle. |

API routes, auth, and raster uploads are in [backend/README.md](backend/README.md). The challenge pipeline is in [ai/README.md](ai/README.md).

## License

© 2026 Geobelic Team. All rights reserved. See [LICENSE](LICENSE).
