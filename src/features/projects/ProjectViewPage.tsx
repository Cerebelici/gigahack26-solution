import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import type { FeatureCollection, Position } from "geojson";
import { resolveApiUrl } from "../../api/client";
import { describeError } from "../../api/errors";
import { getProject } from "../../api/projects";
import { TopBar } from "../../components/TopBar";
import { annotationOverlay } from "../map/annotationOverlay";
import { FieldMap } from "../map/FieldMap";
import { buildFieldData, collectPositions } from "../map/project";
import { MapBanner } from "../map/SidePanels";
import type { ProcessResult } from "../../types/process";
import type { Id, Project } from "../../types/project";
import "./projects.css";

const FEATURE_BOUNDS_PADDING_M = 2;

function storedFeatures(project: Project): FeatureCollection {
  const features = Array.isArray(project.features?.features) ? project.features.features : [];
  return { type: "FeatureCollection", features: features.filter((feature) => feature.geometry) };
}

function featureBounds(collection: FeatureCollection): ProcessResult["boundsEpsg32635"] | null {
  const positions: Position[] = [];
  collection.features.forEach((feature) => feature.geometry && collectPositions(feature.geometry, positions));
  if (positions.length === 0) return null;
  const xs = positions.map(([x]) => x);
  const ys = positions.map(([, y]) => y);
  const pad = FEATURE_BOUNDS_PADDING_M;
  return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
}

/** Imagery plus stored annotations. A `/process-tif` overlay is drawn on top when the latest upload had one. */
function projectResult(project: Project): ProcessResult | null {
  const stored = storedFeatures(project);
  const overlay = annotationOverlay(project.id);
  const features: FeatureCollection = overlay
    ? { type: "FeatureCollection", features: [...stored.features, ...overlay.features] }
    : stored;
  const { raster } = project;
  const bounds = raster?.boundsEpsg32635 ?? featureBounds(features);
  if (!bounds) return null;
  return {
    tiles: raster ? { url: resolveApiUrl(raster.tileUrl), minzoom: raster.minzoom, maxzoom: raster.maxzoom } : null,
    boundsEpsg32635: bounds,
    features,
  };
}

function ProjectSummary({ project, count }: { project: Project; count: number }) {
  return (
    <div className="gbm-project-head">
      <div>
        <div className="gbm-eyebrow">Project</div>
        <h2>{project.name}</h2>
        <p className="gbm-project-meta">
          {count} {count === 1 ? "annotation" : "annotations"} · {project.raster ? "imagery uploaded" : "no imagery"}
        </p>
      </div>
      <Link to={`/projects/${project.id}/edit`} className="gbm-text-btn">
        Edit
      </Link>
    </div>
  );
}

function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className="page">
      <TopBar />
      <main className="projects-main">{children}</main>
    </div>
  );
}

export function ProjectViewRoute() {
  const { id } = useParams();
  return <ProjectViewPage key={id} projectId={id ?? ""} />;
}

function ProjectViewPage({ projectId }: { projectId: Id }) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getProject(projectId)
      .then((loaded) => !cancelled && setProject(loaded))
      .catch((err) => !cancelled && setError(describeError(err, "Could not load the project")));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const result = useMemo(() => (project ? projectResult(project) : null), [project]);
  const data = useMemo(() => (result ? buildFieldData(result) : null), [result]);

  if (error) {
    return (
      <PageShell>
        <Link to="/" className="back-link">
          ← All projects
        </Link>
        <div className="alert-error" role="alert">
          {error}
        </div>
      </PageShell>
    );
  }

  if (!project) {
    return (
      <PageShell>
        <div className="card projects-empty">
          <span className="spinner spinner-dark" aria-hidden="true" />
          <span className="muted">Loading project…</span>
        </div>
      </PageShell>
    );
  }

  const count = result?.features.features.length ?? 0;

  if (!data) {
    return (
      <PageShell>
        <Link to="/" className="back-link">
          ← All projects
        </Link>
        <div className="project-blank">
          <div className="card projects-empty">
            <span className="section-label">{project.name}</span>
            <h1 className="card-title">No imagery or annotations yet</h1>
            <p className="muted">Upload a GeoTIFF to see this project on the map.</p>
            <Link to={`/projects/${project.id}/edit`} className="btn-primary">
              Upload GeoTIFF
            </Link>
          </div>
          <aside className="card gbm-project">
            <ProjectSummary project={project} count={count} />
          </aside>
        </div>
      </PageShell>
    );
  }

  const banner =
    count === 0 ? (
      <MapBanner>No annotations stored for this project yet.</MapBanner>
    ) : !project.raster ? (
      <MapBanner>No imagery uploaded — showing stored annotations only.</MapBanner>
    ) : null;

  return (
    <FieldMap
      data={data}
      overlay={banner}
      planRoute
      projectId={project.id}
      side={
        <aside className="gbm-card gbm-project gbm-float">
          <ProjectSummary project={project} count={count} />
        </aside>
      }
    />
  );
}
