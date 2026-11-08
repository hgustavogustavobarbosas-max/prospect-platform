import { useApi } from "../api";
import { Badge, Card, ErrorBox, Loading, Stat, fmtBRL, fmtUSD, pct } from "../ui";

const ORDER = ["new", "qualified", "contacted", "replying", "handoff", "won", "lost", "suppressed"];

export default function Dashboard() {
  const f = useApi<any>("/v1/metrics/funnel?days=30", 60000);
  const m = useApi<any>("/v1/monitoring/summary", 60000);
  if (f.loading) return <Loading />;
  const d = f.data;
  const max = Math.max(1, ...ORDER.map((s) => d?.leads_by_status?.[s] ?? 0));
  const perDay: { day: string; count: number }[] = d?.leads_per_day ?? [];
  const maxDay = Math.max(1, ...perDay.map((x) => x.count));
  return (
    <>
      <h1 className="text-xl font-bold">Painel (últimos 30 dias)</h1>
      <ErrorBox message={f.error} />
      {d && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Leads criados" value={d.leads_created} />
            <Stat label="Propostas enviadas" value={d.proposals_sent} hint={`Lead → proposta: ${pct(d.conv_lead_to_proposal)}`} />
            <Stat label="Propostas aceitas" value={d.proposals_accepted} hint={`Proposta → aceite: ${pct(d.conv_proposal_to_accept)}`} />
            <Stat label="Receita aceita" value={fmtBRL(d.revenue_cents)} />
            <Stat label="Custo de IA" value={fmtUSD(d.ai_cost_micro_usd)} />
            <Stat label="Custo de APIs" value={fmtUSD(d.api_cost_micro_usd)} />
            <Stat label="Custo por fechamento" value={fmtUSD(d.cost_per_won_micro_usd)} />
            <Stat label="Tokens de IA" value={(d.usage?.llm?.tokens ?? 0).toLocaleString("pt-BR")} />
          </div>
          <Card title="Funil (leads por etapa)">
            <div className="space-y-2">
              {ORDER.map((s) => (
                <div key={s} className="flex items-center gap-3 text-sm">
                  <div className="w-24"><Badge text={s} /></div>
                  <div className="h-5 rounded bg-blue-600" style={{ width: `${((d.leads_by_status?.[s] ?? 0) / max) * 100}%`, minWidth: 2 }} />
                  <div>{d.leads_by_status?.[s] ?? 0}</div>
                </div>
              ))}
            </div>
          </Card>
          <Card title="Novos leads por dia">
            <div className="flex h-24 items-end gap-1">
              {perDay.map((x) => (
                <div key={x.day} title={`${x.day}: ${x.count}`} className="w-3 rounded-t bg-emerald-500" style={{ height: `${(x.count / maxDay) * 100}%` }} />
              ))}
              {perDay.length === 0 && <span className="text-sm text-slate-400">Sem dados no período</span>}
            </div>
          </Card>
        </>
      )}
      <Card title="Alertas do sistema">
        <ErrorBox message={m.error} />
        {m.data?.alerts?.length === 0 && <p className="text-sm text-emerald-700">Tudo certo.</p>}
        <ul className="space-y-1 text-sm">
          {m.data?.alerts?.map((a: any) => (
            <li key={a.code} className="flex gap-2"><Badge text={a.severity} /> {a.message}</li>
          ))}
        </ul>
      </Card>
    </>
  );
}
