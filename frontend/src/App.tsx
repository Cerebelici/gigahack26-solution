import { BrowserRouter, Navigate, Route } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { PublicOnly, RequireAuth } from "./auth/guards";
import { AnimatedRoutes } from "./components/AnimatedRoutes";
import { AuthPage } from "./features/auth/AuthPage";
import { MapPage } from "./features/map/MapPage";
import { DashboardPage } from "./features/projects/DashboardPage";
import { ProjectFormRoute } from "./features/projects/ProjectFormPage";
import { ProjectViewRoute } from "./features/projects/ProjectViewPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AnimatedRoutes>
          <Route element={<PublicOnly />}>
            <Route path="/login" element={<AuthPage key="login" mode="login" />} />
            <Route path="/signup" element={<AuthPage key="signup" mode="signup" />} />
          </Route>
          <Route element={<RequireAuth />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/projects/new" element={<ProjectFormRoute />} />
            <Route path="/projects/:id/edit" element={<ProjectFormRoute />} />
            <Route path="/projects/:id" element={<ProjectViewRoute />} />
          </Route>
          <Route path="/demo" element={<MapPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </AnimatedRoutes>
      </AuthProvider>
    </BrowserRouter>
  );
}
