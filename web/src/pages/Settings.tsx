import { useState } from "react";
import { api, useApi } from "../api";
import { Badge, Btn, Card, ErrorBox, Loading } from "../ui";

export default function Settings() {
  const flags = useApi<any[]>("/v1/system/flags");
  const wa = useApi<any>("/v1/whatsapp/status", 30000);
  const mon = useApi<any>("/v1/monitoring/summary", 30000);
  const [err, setErr] = useState<string | null>(null);
  const sending = flags.data?.find((f) => f.key === "sending_enabled");

  async function toggle() {
    setErr(null);
    try {
      await api("/v1/system/flags/sending_enabled", { method: "PUT", json: { value: !sending?.value } });
      flags.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  if (flags.loading) return <Loading />;
  return (
    <>
      <h1 className="text-xl font-bold">Sistema</h1>
      <ErrorBox message={err ?? flags.error} />
      <Card title="Kill switch de envios">
        <p className="text-sm text-slate-600">Pausa a entrega de todas as mensagens (elas ficam na fila e saem quando você reativar). Requer perfil admin.</p>
        <div className="mt-3 flex items-center gap-3">
          <Badge text={sending?.value ? "envios ativos" : "ENVIOS PAUSADOS"} tone={sending?.value ? "won" : "critical"} />
          <Btn tone={sending?.value ? "danger" : "primary"} onClick={toggle}>{sending?.value ? "Pausar envios" : "Reativar envios"}</Btn>
        </div>
      </Card>
      <Card title="WhatsApp">
        {wa.data && (
          <ul className="space-y-1 text-sm">
            <li>Habilitado: <Badge text={wa.data.enabled ? "sim" : "não"} tone={wa.data.enabled ? "won" : "warning"} /></li>
            {Object.entries(wa.data.configured).map(([k, v]) => <li key={k}>{k}: <Badge text={v ? "ok" : "faltando"} tone={v ? "won" : "critical"} /></li>)}
            <li>Fila pendente: {JSON.stringify(wa.data.pending)}</li>
          </ul>
        )}
      </Card>
      <Card title="Métricas operacionais">
        <pre className="overflow-auto text-xs">{JSON.stringify(mon.data?.metrics ?? {}, null, 2)}</pre>
      </Card>
    </>
  );
}
