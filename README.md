# Geobelic Backend

FastAPI backend for the frontend in `../frontend`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # or requirements.txt for runtime only
cp .env.example .env                  # then edit; .env is gitignored
```

### Configuration

Read from the environment, then from `backend/.env` (real environment variables win).

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://localhost:5432/gigahack` | PostgreSQL with the PostGIS extension. `postgresql://` URLs are used through psycopg 3. A Supabase URL must use the session pooler (`aws-<n>-<region>.pooler.supabase.com:5432`, user `postgres.<project-ref>`) on an IPv4 network; the direct `db.<ref>` host is IPv6-only. Supabase connections require SSL. |
| `JWT_SECRET` | random per process | Signs login tokens. Set it, or every restart logs everyone out. |
| `JWT_TTL_HOURS` | `24` | Token lifetime. |
| `UPLOAD_DIR` | `../uploads` (next to this repo) | Where uploaded rasters and their COGs are stored, one folder per raster id. Keep it outside the repo. |
| `CORS_ORIGINS` | Vite dev and preview origins | Comma-separated allowed origins. |
| `TEST_DATABASE_URL` | `postgresql://localhost:5432/gigahack_test` | Database the API tests truncate and reuse. Never point it at real data. |

### Database

PostgreSQL with PostGIS, for example with Homebrew:

```bash
brew install postgresql@18 postgis
brew services start postgresql@18
createdb gigahack
```

The schema is defined by the SQLAlchemy models in `app/models.py`. On the first request that needs the
database, the app runs `CREATE EXTENSION IF NOT EXISTS postgis` and creates missing tables and indexes.
To do it up front:

```bash
python -m app.db
```

Tables:

- `users`: email (lower-cased, unique), name, argon2id `password_hash`.
- `projects`: `owner_id`, `name`.
- `rasters`: one row per uploaded GeoTIFF: pixel `width`/`height`, the affine `transform`
  `(a, b, c, d, e, f)` (`E = a*x + b*y + c`, `N = d*x + e*y + f` for a pixel corner), the file's CRS
  (`crs_wkt`, and `srid` when it has an EPSG code), EPSG:32635 bounds and tile zooms. A project's current
  raster is its latest one.
- `annotations`: `project_id`, `raster_id` (the image the pixels were measured on), `label`, `shape`
  (`polygon`, `polyline`, `box`), the attributes, and two representations of the same object:
  - `pixel_rings` (JSONB): the model's pixel coordinates exactly as sent, `[[[x, y], ...], ...]`, origin at
    the top-left corner of pixel (0, 0), `y` down. A waste box keeps its original
    `{xtl, ytl, xbr, ybr}` in `pixel_box` and its four corners in `pixel_rings`.
  - `geom` (`geometry(Geometry, 32635)`, GiST index): derived at write time in PostGIS as
    `ST_Transform(ST_SetSRID(ST_Affine(pixels, a, b, d, e, c, f), raster srid), 32635)`, so the pixel size
    and CRS come from the raster itself (2.5 cm tiles in EPSG:32635, the EPSG:4326 mosaic, anything else
    with an EPSG code).

## Run

```bash
uvicorn app.main:app --reload
```

The server listens on `http://localhost:8000`, which is the frontend's default `VITE_API_BASE_URL`.
Interactive docs are at `/docs`. The tile endpoints work without a database; everything else returns
`503` while the database is unreachable.

CORS allows the Vite dev and preview origins (`localhost`/`127.0.0.1` on ports 5173 and 4173) with any
header, including `Authorization`. Override with a comma-separated list:

```bash
CORS_ORIGINS=http://localhost:3000,https://example.com uvicorn app.main:app
```

## API

Endpoints marked 🔒 need `Authorization: Bearer <token>` and return `401` without a valid one. Project
endpoints return `404` for projects the caller does not own. Validation errors are `422`.

### Auth

- `POST /auth/signup` `{ email, password, name }` → `201 { token, user: { id, email, name } }`.
  Password at least 8 characters. `409` if the email is taken.
- `POST /auth/login` `{ email, password }` → `{ token, user }`. `401` on a wrong email or password.
- 🔒 `GET /auth/me` → `{ id, email, name }`
- 🔒 `PATCH /auth/me` `{ name?, password? }` → `{ id, email, name }`

### Projects

- 🔒 `POST /projects` `{ name }` → `201` project summary
- 🔒 `GET /projects` → project summary[] (most recently updated first). No annotations.
- 🔒 `GET /projects/{id}` → project, including its annotations. This is the load used when opening a project.
- 🔒 `PATCH /projects/{id}` `{ name }` → project summary
- 🔒 `DELETE /projects/{id}` → `204` with an empty body. Removes the project, its annotations, and the imagery files. `404` for a project the caller does not own.

A summary, returned by create, list, and rename:

```json
{
  "id": 1,
  "name": "Sireț3 north",
  "raster": null,
  "createdAt": "...",
  "updatedAt": "..."
}
```

Opening a project adds `features`, a FeatureCollection of that project's annotations (see below):

```json
{ "features": { "type": "FeatureCollection", "crs": { "...": "EPSG:32635" }, "features": [] } }
```

`raster` is `null` or `{ id, tileUrl, boundsEpsg32635: [minX, minY, maxX, maxY], minzoom, maxzoom }`.

### Raster upload

🔒 `POST /projects/{id}/raster`, `multipart/form-data` with the file in `file` → the raster object above.
Send one GeoTIFF, or one or more `.zip` files of GeoTIFFs plus the CVAT XML files for those tiles.
Repeat the `file` form field for each zip. Every tile, from every zip, is mosaicked by its coordinates
into one orthophoto: neighbouring tiles meet on the ground, and the gap between them stays transparent.
The upload becomes the project's current raster, stored in `UPLOAD_DIR/<raster id>/` and converted to a
COG with overviews. Zooming still requests `{z}/{x}/{y}` tiles of that one image.

Shapes from each zip's XML are stored as the project's annotations, in the mosaic's pixel grid, replacing
the previous ones. An XML `<image name>` matches a TIFF from the same zip by file name (`left.tif`, or
`tiles/left.tif`). A single GeoTIFF still takes the shapes in `annotations.xml` that lie on it, placed by
where their tile (`siret3_rNNN_cNNN.tif`) sits on the challenge grid. A shape with an unusable attribute is
stored without its attributes; one with unusable geometry is skipped and logged. An upload with no shapes
leaves the existing annotations alone.

Projects uploaded before this have none. Fill them once with `python -m app.backfill_annotations`; it only
touches projects without annotations.

### Annotations

🔒 `POST /projects/{id}/annotations` → `201` GeoJSON Feature. Pixel coordinates on the project's current
raster (`409` if it has none yet):

```json
{
  "label": "vineyard",
  "rings": [[x, y], ...],
  "vineyard_id": "V01", "row_id": null, "row_structure": null, "interrow_cover": null,
  "length_m": null, "grapevine_count": null, "area_m2": null, "area_ha": null
}
```

- `label`: `vineyard` · `waste` · `row` · `interrow_area`.
- `row` is a polyline: one ring of at least 2 points → `LineString`.
- `vineyard`, `interrow_area`, and `waste` are polygons: at least 3 points, closing point optional. `rings`
  may also be a list of rings (outer first, then holes).
- `waste` may instead send `box: { xtl, ytl, xbr, ybr }`.
- `row_structure`: `regular` · `disrupted` · `unassessable`. `interrow_cover`: `bare_soil` · `vegetation`
  · `mixed` · `unassessable`.

🔒 `GET /projects/{id}/annotations` → FeatureCollection. Geometry is EPSG:32635 metres. Properties:
`id`, `label`, the attributes above, `pixelRings` (always a list of rings, as stored), `rasterId`, and
`pixelBox` for boxes.

### Route planning (stub)

🔒 `POST /projects/{id}/routes` `{ routeType }` →
`200 { "route": null, "detail": "Route planning is not implemented yet." }`. No route is computed yet.

### `POST /process-tif`

Stores a georeferenced TIFF without a project and returns where to fetch map tiles for it. The upload is
streamed to `UPLOAD_DIR/<id>/`. If it is not already a Cloud Optimized GeoTIFF with overviews, it is
converted to one, which can take minutes for very large mosaics.

Request: `multipart/form-data` with the TIFF in the `file` field. Any content type is accepted
(`image/tiff`, `image/x-tiff`, `application/octet-stream`, ...); the file is validated by its TIFF
magic bytes (classic TIFF and BigTIFF).

```bash
curl -F "file=@tile.tif" http://localhost:8000/process-tif
```

Responses:

- `200`:
  ```json
  {
    "id": "<uuid hex>",
    "boundsEpsg32635": [minX, minY, maxX, maxY],
    "tileUrl": "http://localhost:8000/tiles/<id>/{z}/{x}/{y}.png",
    "minzoom": 16,
    "maxzoom": 22
  }
  ```
  Bounds are reprojected to EPSG:32635 from the file's CRS. `maxzoom` matches the native
  resolution; at `minzoom` the whole raster fits in a single tile.
- `400`: `{"detail": "..."}` when the file is missing, empty, not a TIFF, unreadable, has no
  georeferencing, or cannot be reprojected.

### `GET /tiles/{id}/{z}/{x}/{y}.png`

256×256 XYZ Web Mercator (EPSG:3857) PNG tile for a stored raster, for MapLibre raster sources.
Only the overview level matching `z` is read, windowed to the tile. Tiles outside the raster are
transparent. Unknown ids return `404`. Tiles are public: raster ids are random 128-bit values.

## Tests

```bash
pytest
```

The API tests need PostgreSQL with PostGIS. They create `TEST_DATABASE_URL` if it is missing and
truncate its tables; uploads go to a temporary directory.
