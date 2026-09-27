import { useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { describeError } from "../../api/errors";
import { deleteProject, listProjects } from "../../api/projects";
import { useAuth } from "../../auth/AuthContext";
import { CountUp } from "../../components/CountUp";
import { TopBar } from "../../components/TopBar";
import type { Project } from "../../types/project";
import "./projects.css";

function annotationCount(project: Project): number | null {
  return Array.isArray(project.features?.features) ? project.features.features.length : null;
}

function ProjectCard({
  project,
  index,
  deleting,
  onDelete,
}: {
  project: Project;
  index: number;
  deleting: boolean;
  onDelete: (project: Project) => void;
}) {
  const count = annotationCount(project);
  return (
    <li className="card project-card" style={{ "--i": index } as CSSProperties}>
      <div className="project-card-head">
        <span className={project.raster ? "status-chip is-ready" : "status-chip"}>
          {project.raster ? "Imagery ready" : "No imagery"}
        </span>
        {count !== null && (
          <span className="muted project-card-meta">
            <CountUp value={count} /> {count === 1 ? "annotation" : "annotations"}
          </span>
        )}
      </div>
      <h2 className="project-card-title" title={project.name}>
        {project.name}
      </h2>
      <div className="project-card-actions">
        <Link to={`/projects/${project.id}`} className="btn-primary btn-small">
          Open map
        </Link>
        <Link to={`/projects/${project.id}/edit`} className="btn-ghost">
          Edit
        </Link>
        <button type="button" className="btn-ghost is-danger" disabled={deleting} onClick={() => onDelete(project)}>
          {deleting ? "Deleting…" : "Delete"}
        </button>
      </div>
    </li>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<Project["id"] | null>(null);

  async function onDelete(project: Project) {
    if (!window.confirm(`Delete “${project.name}”? This removes its imagery and annotations.`)) return;
    setDeletingId(project.id);
    setError(null);
    try {
      await deleteProject(project.id);
      setProjects((current) => current?.filter((item) => item.id !== project.id) ?? current);
    } catch (err) {
      setError(describeError(err, "Could not delete the project"));
    } finally {
      setDeletingId(null);
    }
  }

  useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((list) => !cancelled && setProjects(list))
      .catch((err) => !cancelled && setError(describeError(err, "Could not load projects")));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="page">
      <TopBar />

      <main className="projects-main">
        <section className="dashboard-head">
          <div>
            <span className="section-label">Signed in as {user?.name || user?.email}</span>
            <h1 className="dashboard-title">Your projects</h1>
          </div>
          <Link to="/projects/new" className="btn-primary">
            New project
          </Link>
        </section>

        {error && (
          <div className="alert-error" role="alert">
            {error}
          </div>
        )}

        {!error && projects === null && (
          <div className="card projects-empty">
            <span className="spinner spinner-dark" aria-hidden="true" />
            <span className="muted">Loading projects…</span>
          </div>
        )}

        {projects?.length === 0 && (
          <div className="card projects-empty">
            <h2 className="card-title">No projects yet</h2>
            <p className="muted">Create a project, then upload a GeoTIFF to see it on the map.</p>
            <Link to="/projects/new" className="btn-primary">
              Create your first project
            </Link>
          </div>
        )}

        {projects && projects.length > 0 && (
          <ul className="project-grid">
            {projects.map((project, index) => (
              <ProjectCard
                key={project.id}
                project={project}
                index={index}
                deleting={deletingId === project.id}
                onDelete={onDelete}
              />
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
