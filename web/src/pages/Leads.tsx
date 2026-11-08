import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api";
import { Badge, Card, ErrorBox, Loading } from "../ui";

const STATUS = ["", "new", "qualified", "contacted", "replying", "handoff", "won", "lost", "suppressed"];

export default function Leads() {
  const [status, setStatus] = useState("");
  const [tier, setTier] = useState("");
  const q = new URLSearchParams({ limit: "100" });
  if (status) q.set("status", status);
  if (tier) q.set("tier", tier);
  const { data, error, loading } = useApi<any[]>(`/v1/leads?${q}`);
  return (
    <>
      <h1 className="text-xl font-bold">Leads</h1>
      <div className="flex gap-2 text-sm">
        <select className="rounded-lg border p-2" value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUS.map((s) => <option key={s} value={s}>{s || "Todas as etapas"}</option>)}
        </select>
        <select className="rounded-lg border p-2" value={tier} onChange={(e) => setTier(e.target.value)}>
          {["", "A", "B", "C"].map((t) => <option key={t} value={t}>{t ? `Perfil ${t}` : "Todos os perfis"}</option>)}
        </select>
      </div>
      <ErrorBox message={error} />
      {loading ? <Loading /> : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-500"><tr><th className="p-2">Lead</th><th>Etapa</th><th>Perfil</th><th>Score</th><th>Justificativa</th></tr></thead>
              <tbody>
                {data?.map((l) => (
                  <tr key={l.id} className="border-t">
                    <td className="p-2"><Link className="text-blue-700 underline" to={`/leads/${l.id}`}>{l.id.slice(0, 8)}</Link></td>
                    <td><Badge text={l.status} /></td>
                    <td><Badge text={l.tier} /></td>
                    <td>{l.score ?? "-"}</td>
                    <td className="max-w-md truncate text-slate-600">{l.justification}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data?.length === 0 && <p className="p-4 text-sm text-slate-500">Nenhum lead.</p>}
          </div>
        </Card>
      )}
    </>
  );
}
