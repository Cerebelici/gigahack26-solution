import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { describeError } from "../../api/errors";
import { useAuth } from "../../auth/AuthContext";
import { TopBar } from "../../components/TopBar";
import { HeroCopy, HeroStage } from "../hero/Hero";
import "./auth.css";

type Mode = "login" | "signup";

const COPY: Record<Mode, { label: string; title: string; lede: string; submit: string; busy: string }> = {
  login: {
    label: "Welcome back",
    title: "Sign in",
    lede: "Open your vineyard projects, imagery and annotations.",
    submit: "Sign in",
    busy: "Signing in…",
  },
  signup: {
    label: "Get started",
    title: "Create an account",
    lede: "Projects hold one GeoTIFF and the annotations drawn on it.",
    submit: "Create account",
    busy: "Creating account…",
  },
};

export function AuthPage({ mode }: { mode: Mode }) {
  const navigate = useNavigate();
  const { login, signup } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const copy = COPY[mode];

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") await signup(email.trim(), password, name.trim());
      else await login(email.trim(), password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(describeError(err, mode === "signup" ? "Sign-up failed" : "Sign-in failed"));
      setBusy(false);
    }
  }

  return (
    <>
      <HeroStage />
      <div className="page hero-page">
        <TopBar />

        <main className="hero-main">
          <HeroCopy />
          <form className="card auth-card" onSubmit={onSubmit}>
            <div className="auth-head">
              <span className="section-label">{copy.label}</span>
              <h2 className="card-title">{copy.title}</h2>
              <p className="muted auth-lede">{copy.lede}</p>
            </div>

            {mode === "signup" && (
              <label className="field">
                <span className="field-label">Name</span>
                <input
                  className="input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  required
                  disabled={busy}
                />
              </label>
            )}

            <label className="field">
              <span className="field-label">Email</span>
              <input
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
                disabled={busy}
              />
            </label>

            <label className="field">
              <span className="field-label">Password</span>
              <input
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                required
                disabled={busy}
              />
            </label>

            {error && (
              <div className="alert-error" role="alert">
                {error}
              </div>
            )}

            <button type="submit" className="btn-primary auth-submit" disabled={busy}>
              {busy && <span className="spinner" aria-hidden="true" />}
              {busy ? copy.busy : copy.submit}
            </button>

            <p className="muted auth-switch">
              {mode === "login" ? (
                <>
                  No account yet? <Link to="/signup">Create one</Link>
                </>
              ) : (
                <>
                  Already registered? <Link to="/login">Sign in</Link>
                </>
              )}
            </p>
          </form>
        </main>
      </div>
    </>
  );
}
