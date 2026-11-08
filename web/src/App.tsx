import type { ReactNode } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { getToken, setToken } from "./api";
import Compliance from "./pages/Compliance";
import Dashboard from "./pages/Dashboard";
import Inbox from "./pages/Inbox";
import LeadDetail from "./pages/LeadDetail";
import Leads from "./pages/Leads";
import Login from "./pages/Login";
import Plans from "./pages/Plans";
import Proposals from "./pages/Proposals";
import Settings from "./pages/Settings";

const NAV: [string, string][] = [
  ["/", "Painel"], ["/inbox", "Atendimento"], ["/leads", "Leads"], ["/proposals", "Propostas"],
  ["/plans", "Planos"], ["/compliance", "Conformidade"], ["/settings", "Sistema"],
];

function Layout({ children }: { children: ReactNode }) {
  const logout = () => {
    setToken(null);
    window.location.href = "/login";
  };
  return (
    <div className="min-h-screen md:flex">
      <nav className="flex gap-1 overflow-x-auto bg-slate-900 p-2 text-sm text-slate-200 md:w-52 md:flex-col md:p-4">
        <div className="hidden pb-4 text-lg font-bold text-white md:block">Prospect CRM</div>
        {NAV.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === "/"}
            className={({ isActive }) => `whitespace-nowrap rounded-lg px-3 py-2 ${isActive ? "bg-blue-700 text-white" : "hover:bg-slate-800"}`}>
            {label}
          </NavLink>
        ))}
        <button onClick={logout} className="rounded-lg px-3 py-2 text-left hover:bg-slate-800 md:mt-auto">Sair</button>
      </nav>
      <main className="flex-1 space-y-4 p-4 md:p-6">{children}</main>
    </div>
  );
}

function Private({ children }: { children: ReactNode }) {
  return getToken() ? <Layout>{children}</Layout> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Private><Dashboard /></Private>} />
      <Route path="/inbox" element={<Private><Inbox /></Private>} />
      <Route path="/leads" element={<Private><Leads /></Private>} />
      <Route path="/leads/:id" element={<Private><LeadDetail /></Private>} />
      <Route path="/proposals" element={<Private><Proposals /></Private>} />
      <Route path="/plans" element={<Private><Plans /></Private>} />
      <Route path="/compliance" element={<Private><Compliance /></Private>} />
      <Route path="/settings" element={<Private><Settings /></Private>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
