import { useState } from "react";
import { Link } from "react-router-dom";
import { api, useApi } from "../api";
import { Badge, Btn, Card, ErrorBox, Loading, fmtBRL, fmtDate } from "../ui";

export default function Proposals() {
  const { data, error, loading, reload } = useApi<any[]>("/v1/opportunities?limit=100");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function act(fn: () => Promise<any>, ok: (r: any) => string) {
    setErr(null);
    setMsg(null);
    try {
      const r = await fn();
      setMsg(ok(r));
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  const post = (path: string, json: unknown = {}) => api<any>(path, { method: "POST", json });

  return (
    <>
      <h1 className="text-xl font-bold">Propostas e entregas</h1>
      <ErrorBox message={err ?? error} />
      {msg && <div className="break-all rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{msg}</div>}
      {loading ? <Loading /> : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-500"><tr><th className="p-2">Lead</th><th>Plano</th><th>Valor</th><th>Status</th><th>Aceite</th><th>NPS</th><th>Ações</th></tr></thead>
              <tbody>
                {data?.map((o) => (
                  <tr key={o.id} className="border-t align-top">
                    <td className="p-2"><Link className="text-blue-700 underline" to={`/leads/${o.lead_id}`}>{o.lead_id.slice(0, 8)}</Link></td>
                    <td>{o.plan}</td><td>{fmtBRL(o.value_cents)}</td><td><Badge text={o.status} /></td>
                    <td>{fmtDate(o.accepted_at)}</td><td>{o.nps_score ?? "-"}</td>
                    <td className="flex flex-wrap gap-1 py-1">
                      <Btn tone="ghost" onClick={() => act(() => post(`/v1/opportunities/${o.id}/proposal`), (r) => `Proposta: ${window.location.origin}${new URL(r.url).pathname}`)}>Proposta</Btn>
                      <Btn tone="ghost" onClick={() => act(() => post(`/v1/opportunities/${o.id}/kickoff`), (r) => `Briefing: ${r.briefing_url}`)}>Briefing</Btn>
                      <Btn tone="ghost" onClick={() => act(() => post(`/v1/opportunities/${o.id}/preview`), (r) => `Prévia: ${r.url}`)}>Prévia</Btn>
                      <Btn tone="ghost" onClick={() => act(() => post(`/v1/opportunities/${o.id}/charge`), () => "Cobrança criada.")}>Cobrar</Btn>
                      <Btn tone="ghost" onClick={() => {
                        const url = window.prompt("URL final do site entregue:");
                        if (url) act(() => post(`/v1/opportunities/${o.id}/deliver`, { url }), () => "Entrega registrada; uptime ativado.");
                      }}>Entregar</Btn>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data?.length === 0 && <p className="p-4 text-sm text-slate-500">Nenhuma oportunidade.</p>}
          </div>
        </Card>
      )}
    </>
  );
}
