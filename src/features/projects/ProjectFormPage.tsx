import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { describeError } from "../../api/errors";
import { processTif } from "../../api/processTif";
import { createProject, getProject, renameProject, uploadRaster } from "../../api/projects";
import { TopBar } from "../../components/TopBar";
import { setAnnotationOverlay } from "../map/annotationOverlay";
import { annotationsToFeatures, extentFromBounds, parseAnnotationDocument } from "../map/tiffAnnotations";
import type { Id, Project } from "../../types/project";
import { GeoTiffDropzone } from "./GeoTiffDropzone";
import "./projects.css";

type Phase = { kind: "idle" } | { kind: "saving" } | { kind: "uploading"; fraction: number };

function phaseLabel(phase: Phase, fallback: string): string {
  if (phase.kind === "saving") return "Saving project…";
  if (phase.kind === "uploading") {
    return phase.fraction < 1 ? `Uploading ${Math.round(phase.fraction * 100)}%…` : "Processing imagery…";
  }
  return fallback;
}

const SCAN_BARS = Array.from({ length: 14 }, (_, i) => i);

function UploadProgress({ fraction }: { fraction: number }) {
  const processing = fraction >= 1;
  const percent = Math.round(fraction * 100);
  return (
    <div className="upload-progress">
      <div className="upload-progress-head">
        <span>{processing ? "Processing imagery" : "Uploading GeoTIFF"}</span>
        {!processing && <span className="upload-progress-value">{percent}%</span>}
      </div>
      <div
        className={processing ? "upload-track is-indeterminate" : "upload-track"}
        role="progressbar"
        aria-label={processing ? "Processing imagery" : "Upload progress"}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={processing ? undefined : percent}
      >
        <span className="upload-fill" style={processing ? undefined : { transform: `scaleX(${fraction})` }} />
      </div>
      {processing && (
        <div className="upload-scan" aria-hidden="true">
          {SCAN_BARS.map((i) => (
            <span key={i} style={{ "--i": i } as CSSProperties} />
          ))}
        </div>
      )}
    </div>
  );
}

function readError(state: unknown): string | null {
  if (!state || typeof state !== "object" || !("error" in state)) return null;
  const error = (state as { error?: unknown }).error;
  return typeof error === "string" ? error : null;
}

function rasterSize(project: Project): string | null {
  if (!project.raster) return null;
  const [minX, minY, maxX, maxY] = project.raster.boundsEpsg32635;
  return `${(maxX - minX).toFixed(1)} × ${(maxY - minY).toFixed(1)} m`;
}

export function ProjectFormRoute() {
  const { id } = useParams();
  return <ProjectFormPage key={id ?? "new"} projectId={id ?? null} />;
}

function ProjectFormPage({ projectId }: { projectId: Id | null }) {
  const navigate = useNavigate();
  const location = useLocation();
  const isEdit = projectId !== null;

  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState<string | null>(() => readError(location.state));

  useEffect(() => {
    if (projectId === null) return;
    let cancelled = false;
    getProject(projectId)
      .then((loaded) => {
        if (cancelled) return;
        setProject(loaded);
        setName(loaded.name);
      })
      .catch((err) => !cancelled && setLoadError(describeError(err, "Could not load the project")));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const busy = phase.kind !== "idle";
  const trimmed = name.trim();
  const renamed = isEdit && project !== null && trimmed !== project.name;
  const canSubmit = !busy && trimmed !== "" && (!isEdit || (project !== null && (renamed || file !== null)));

  async function upload(id: Id, chosen: File) {
    setPhase({ kind: "uploading", fraction: 0 });
    // Tiles still come from the project raster. /process-tif adds pixel annotations when the body is multipart.
    const [raster, processed] = await Promise.all([
      uploadRaster(id, chosen, (fraction) => setPhase({ kind: "uploading", fraction })),
      processTif(chosen),
    ]);
    const features = processed.annotations
      ? annotationsToFeatures(parseAnnotationDocument(processed.annotations), extentFromBounds(raster.boundsEpsg32635))
      : null;
    setAnnotationOverlay(id, features);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setError(null);

    if (!isEdit) {
      setPhase({ kind: "saving" });
      let created: Project;
      try {
        created = await createProject(trimmed);
      } catch (err) {
        setError(describeError(err, "Could not create the project"));
        setPhase({ kind: "idle" });
        return;
      }
      if (file) {
        try {
          await upload(created.id, file);
        } catch (err) {
          // The project exists now; retry the upload from its edit page instead of creating a duplicate.
          const message = `Project created, but the upload failed: ${describeError(err, "Upload failed")}`;
          navigate(`/projects/${created.id}/edit`, { replace: true, state: { error: message } });
          return;
        }
      }
      navigate(`/projects/${created.id}`);
      return;
    }

    try {
      if (renamed) {
        setPhase({ kind: "saving" });
        const updated = await renameProject(projectId, trimmed);
        setProject((current) => (current ? { ...current, name: updated.name ?? trimmed } : current));
      }
      if (file) await upload(projectId, file);
      navigate(`/projects/${projectId}`);
    } catch (err) {
      setError(describeError(err, "Could not save the project"));
      setPhase({ kind: "idle" });
    }
  }

  const submitLabel = isEdit ? "Save changes" : file ? "Create and upload" : "Create project";
  const size = project ? rasterSize(project) : null;

  return (
    <div className="page">
      <TopBar />

      <main className="projects-main projects-narrow">
        <Link to={isEdit ? `/projects/${projectId}` : "/"} className="back-link">
          ← {isEdit ? "Back to map" : "All projects"}
        </Link>

        {loadError ? (
          <div className="alert-error" role="alert">
            {loadError}
          </div>
        ) : isEdit && !project ? (
          <div className="card projects-empty">
            <span className="spinner spinner-dark" aria-hidden="true" />
            <span className="muted">Loading project…</span>
          </div>
        ) : (
          <form className="card form-card" onSubmit={onSubmit}>
            <div className="upload-head">
              <span className="section-label">{isEdit ? "Edit project" : "New project"}</span>
              <h1 className="card-title">{isEdit ? project?.name : "Create a project"}</h1>
              <p className="muted upload-lede">
                A project holds one GeoTIFF orthophoto and the annotations stored for it.
              </p>
            </div>

            <label className="field">
              <span className="field-label">Project name</span>
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Sireț3 · r018 c010"
                required
                disabled={busy}
              />
            </label>

            <div className="field">
              <span className="field-label">{project?.raster ? "Replace imagery" : "GeoTIFF imagery (optional)"}</span>
              {project?.raster && (
                <div className="upload-file">
                  <span className="upload-file-icon">MAP</span>
                  <div className="upload-file-meta">
                    <strong>Imagery uploaded</strong>
                    <span className="muted">
                      {size} · zoom {project.raster.minzoom}–{project.raster.maxzoom}
                    </span>
                  </div>
                </div>
              )}
              <GeoTiffDropzone
                file={file}
                disabled={busy}
                onChange={(next) => {
                  setError(null);
                  setFile(next);
                }}
                onReject={setError}
              />
            </div>

            {error && (
              <div className="alert-error" role="alert">
                {error}
              </div>
            )}

            <button type="submit" className="btn-primary upload-submit" disabled={!canSubmit}>
              {busy && <span className="spinner" aria-hidden="true" />}
              {phaseLabel(phase, submitLabel)}
            </button>
            {phase.kind === "uploading" && <UploadProgress fraction={phase.fraction} />}
            {phase.kind === "uploading" && (
              <p className="muted form-note">Large GeoTIFFs are converted on the server; this can take several minutes.</p>
            )}
          </form>
        )}
      </main>
    </div>
  );
}
