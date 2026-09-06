import {
  Activity,
  BarChart3,
  Bell,
  GitBranch,
  LayoutDashboard,
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
  Overview,
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
          <NavLink to="/overview">
            <LayoutDashboard />
            Overview
          </NavLink>
          <NavLink to="/incidents">
            <Bell />
            Incidents
          </NavLink>
          <NavLink to="/topology">
            <Network />
            Topology
          </NavLink>
          <NavLink to="/runs">
            <ListChecks />
            Agent Runs
          </NavLink>
          <NavLink to="/integrations">
            <Radio />
            Data Sources
          </NavLink>
          <NavLink to="/evaluations">
            <BarChart3 />
            Evaluations
          </NavLink>
        </nav>
        <div className="rail-foot">
          <div className="live-dot" />
          SIMULATOR ONLINE<small>Deterministic lab</small>
        </div>
      </aside>
      <main>
        <header>
          <div className="crumb">
            <GitBranch />
            RELAY / NOC CONSOLE
          </div>
          <div className="header-state">
            <Activity /> AUTONOMY BOUNDED <ShieldCheck /> HUMAN-GATED WRITES
          </div>
        </header>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/overview" element={<Overview />} />
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
