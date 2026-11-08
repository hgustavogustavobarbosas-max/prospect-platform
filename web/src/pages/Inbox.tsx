import { Link } from "react-router-dom";
import { useApi } from "../api";
import { Badge, Card, ErrorBox, Loading } from "../ui";

export default function Inbox() {
  const { data, error, loading } = useApi<any[]>("/v1/inbox", 20000);
  return (
    <>
      <h1 className="text-xl font-bold">Atendimento humano</h1>
      <p className="text-sm text-slate-500">Conversas em que o agente passou a vez. Atualiza a cada 20 s.</p>
      <ErrorBox message={error} />
      {loading ? <Loading /> : (
        <div className="space-y-2">
          {data?.length === 0 && <Card>Nenhuma conversa aguardando atendente.</Card>}
          {data?.map((r) => (
            <Link key={r.conversation_id} to={`/leads/${r.lead_id}`} className="block">
              <Card className={r.sla_breached ? "border-red-300" : ""}>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge text={r.tier} />
                  {r.waiting_for_human ? <Badge text={`aguardando ${r.minutes_waiting} min`} tone={r.sla_breached ? "critical" : "warning"} /> : <Badge text="respondido" tone="info" />}
                  {r.sla_breached && <Badge text="SLA estourado" tone="critical" />}
                </div>
                <p className="mt-2 text-sm text-slate-700">{r.last_message ?? "(sem mensagens)"}</p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
