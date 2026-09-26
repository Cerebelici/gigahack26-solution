import { useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { describeError } from "../../api/errors";
import { listProjects } from "../../api/projects";
import { useAuth } from "../../auth/AuthContext";
import { CountUp } from "../../components/CountUp";
import { TopBar } from "../../components/TopBar";
import type { Project } from "../../types/project";
import "./projects.css";

function annotationCount(project: Project): number | null {
  return Array.isArray(project.features?.features) ? project.features.features.length : null;
}

function ProjectCard({ project, index }: { project: Project; index: number }) {
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
      </div>
    </li>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
              <ProjectCard key={project.id} project={project} index={index} />
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
