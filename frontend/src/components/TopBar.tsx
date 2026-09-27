import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

function VineMark() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 21c0-6 1.6-9.6 6-12.4-5.2 0-7.8 2.6-8.6 6-.9-2.6-2.6-4.4-5.4-4.4.9 3.4 3.4 5.2 6.2 6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="17.5" cy="4.5" r="1.6" fill="currentColor" />
    </svg>
  );
}

const pillClass = ({ isActive }: { isActive: boolean }) => (isActive ? "pill active" : "pill");

function CollapseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M14.5 6 8.5 12l6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

interface TopBarProps {
  /** Map view: bar is slid shut to the left. */
  collapsed?: boolean;
  /** Map view only. Omit on pages where the bar stays open. */
  onToggle?: () => void;
}

export function TopBar({ collapsed = false, onToggle }: TopBarProps = {}) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function onLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <header className="topbar">
      {onToggle && (
        <button
          type="button"
          className="topbar-collapse"
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Show navigation" : "Collapse navigation"}
          onClick={onToggle}
        >
          <span className="topbar-collapse-icon">
            <CollapseIcon />
          </span>
        </button>
      )}
      <div className="topbar-rest">
        <NavLink to="/" className="topbar-brand">
          <span className="topbar-mark">
            <VineMark />
          </span>
          <span className="topbar-wordmark">
            <strong>Geobelic</strong>
            <span className="muted">Vineyard field</span>
          </span>
        </NavLink>

        <nav className="topbar-nav" aria-label="Main" inert={collapsed ? true : undefined}>
          {user ? (
            <>
              <NavLink to="/" end className={pillClass}>
                Projects
              </NavLink>
              <NavLink to="/projects/new" className={pillClass}>
                New project
              </NavLink>
            </>
          ) : (
            <>
              <NavLink to="/login" className={pillClass}>
                Sign in
              </NavLink>
              <NavLink to="/demo" className={pillClass}>
                Sample
              </NavLink>
            </>
          )}
        </nav>

        {user ? (
          <div className="topbar-user" inert={collapsed ? true : undefined}>
            <span className="topbar-avatar" aria-hidden="true">
              {(user.name || user.email).trim().charAt(0).toUpperCase()}
            </span>
            <span className="topbar-user-meta">
              <strong>{user.name || user.email}</strong>
              {user.name && <span className="muted">{user.email}</span>}
            </span>
            <button type="button" className="btn-ghost" onClick={onLogout}>
              Log out
            </button>
          </div>
        ) : (
          <span className="topbar-status" inert={collapsed ? true : undefined}>
            Sireț3 · EPSG:32635
          </span>
        )}
      </div>
    </header>
  );
}
