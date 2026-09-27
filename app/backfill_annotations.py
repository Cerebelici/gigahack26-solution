"""Store catalog annotations for projects whose current raster has none.

Uploads made before annotations were stored with the raster have none. Run once:

    python -m app.backfill_annotations
"""

from sqlalchemy import func, select

from app.db import ensure_schema, get_db
from app.models import Annotation, Project
from app.routers.projects import _latest_rasters, store_catalog_annotations


def main() -> None:
    ensure_schema()
    db = next(get_db())
    try:
        annotated = set(db.scalars(select(Annotation.project_id).group_by(Annotation.project_id)))
        projects = [project for project in db.scalars(select(Project).order_by(Project.id)) if project.id not in annotated]
        rasters = _latest_rasters(db, [project.id for project in projects])
        for project in projects:
            raster = rasters.get(project.id)
            if raster is None:
                continue
            stored = store_catalog_annotations(db, project, raster)
            if stored:
                project.updated_at = func.now()
            db.commit()
            print(f"project {project.id} {project.name!r}: {stored} annotations")
    finally:
        db.close()


if __name__ == "__main__":
    main()
