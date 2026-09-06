import {
  Activity,
  BarChart3,
  Bell,
  GitBranch,
  Home as HomeIcon,
  ListChecks,
  Network,
  Radio,
  ShieldCheck,
} from "lucide-react";
import { NavLink, Route, Routes } from "react-router-dom";
import {
  Evaluations,
  Home,
  IncidentPage,
  Incidents,
  Runs,
  TopologyPage,
  Integrations,
} from "./pages";
export default function App() {
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <div className="brand-mark">
            <Radio />
          </div>
          <div>
            <b>RELAY</b>
            <span>NETWORK OPERATIONS</span>
          </div>
        </div>
        <nav>
          <NavLink to="/">
            <HomeIcon />
            Home
          </NavLink>
          <NavLink to="/incidents">
            <Bell />
            Investigations
          </NavLink>
          <NavLink to="/topology">
            <Network />
            Network
          </NavLink>
          <NavLink to="/runs">
            <ListChecks />
            Runs
          </NavLink>
          <NavLink to="/integrations">
            <Radio />
            Sources
          </NavLink>
          <NavLink to="/evaluations">
            <BarChart3 />
            Evaluation
          </NavLink>
        </nav>
      </aside>
      <main>
        <header>
          <div className="crumb">
            <GitBranch />
            RELAY / INVESTIGATIONS
          </div>
          <div className="header-state">
            <Activity /> SOURCE-BACKED EVIDENCE <ShieldCheck /> HUMAN-GATED WRITES
          </div>
        </header>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/incidents" element={<Incidents />} />
          <Route path="/incidents/:id" element={<IncidentPage />} />
          <Route path="/topology" element={<TopologyPage />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/integrations" element={<Integrations />} />
          <Route path="/evaluations" element={<Evaluations />} />
        </Routes>
      </main>
    </div>
  );
}
