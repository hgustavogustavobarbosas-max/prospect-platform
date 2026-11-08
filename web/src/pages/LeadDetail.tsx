import { FormEvent, useState } from "react";
import { useParams } from "react-router-dom";
import { api, useApi } from "../api";
import { Badge, Btn, Card, ErrorBox, Loading, fmtBRL, fmtDate } from "../ui";

export default function LeadDetail() {
  const { id } = useParams();
  const lead = useApi<any>(`/v1/leads/${id}`);
  const tl = useApi<any>(`/v1/leads/${id}/timeline`, 15000);
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setErr(null);
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      tl.reload();
      lead.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  const send = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    run(() => api(`/v1/leads/${id}/messages`, { method: "POST", json: { text } }), "Mensagem na fila de envio.").then(() => setText(""));
  };

  if (lead.loading || tl.loading) return <Loading />;
  const l = lead.data;
  const conv = tl.data?.conversation;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold">Lead {String(id).slice(0, 8)}</h1>
        <Badge text={l?.status} /> <Badge text={l?.tier} /> <span className="text-sm text-slate-500">score {l?.score ?? "-"}</span>
      </div>
      <ErrorBox message={err ?? lead.error ?? tl.error} />
      {msg && <div className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{msg}</div>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Conversa" className="lg:col-span-2">
          <div className="max-h-[28rem] space-y-2 overflow-y-auto">
            {tl.data?.interactions?.map((i: any) => (
              <div key={i.id} className={`max-w-[85%] rounded-xl p-2 text-sm ${i.direction === "in" ? "bg-slate-100" : "ml-auto bg-blue-50"}`}>
                <div>{i.content}</div>
                <div className="mt-1 text-[11px] text-slate-400">{fmtDate(i.at)} {i.kind && `· ${i.kind}`} {i.delivery && `· ${i.delivery}`}</div>
              </div>
            ))}
            {tl.data?.interactions?.length === 0 && <p className="text-sm text-slate-500">Sem mensagens.</p>}
          </div>
          <form onSubmit={send} className="mt-3 flex gap-2">
            <input className="flex-1 rounded-lg border p-2 text-sm" value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} placeholder="Responder como atendente (janela de 24h)" />
            <Btn>Enviar</Btn>
          </form>
          {conv && (
            <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
              Conversa: <Badge text={conv.status} /> · {conv.tokens_used} tokens
              {conv.status === "handoff" && (
                <Btn tone="ghost" onClick={() => run(() => api(`/v1/conversations/${conv.id}/return-to-agent`, { method: "POST" }), "Devolvido ao agente.")}>Devolver ao agente</Btn>
              )}
            </div>
          )}
        </Card>
        <div className="space-y-4">
          <Card title="Por que esta pontuação">
            <p className="text-sm text-slate-700">{l?.justification}</p>
            <ul className="mt-2 text-xs text-slate-500">
              {Object.entries(l?.score_breakdown ?? {}).map(([k, v]) => <li key={k}>{k}: {String(v)}</li>)}
            </ul>
          </Card>
          <Card title="Dados coletados pelo agente">
            <pre className="whitespace-pre-wrap text-xs">{JSON.stringify(conv?.qualification ?? {}, null, 2)}</pre>
          </Card>
          <Card title="Oportunidades">
            {tl.data?.opportunities?.map((o: any) => (
              <div key={o.id} className="space-y-1 border-b py-2 text-sm last:border-0">
                <div>{o.plan} · {fmtBRL(o.value_cents)} · <Badge text={o.status} /></div>
                <div className="flex gap-2">
                  <Btn tone="ghost" onClick={() => run(async () => {
                    const r = await api<any>(`/v1/opportunities/${o.id}/proposal`, { method: "POST", json: {} });
                    setMsg(`Proposta: ${r.url}`);
                  }, "Proposta gerada.")}>Gerar</Btn>
                  <Btn tone="ghost" onClick={() => run(() => api(`/v1/opportunities/${o.id}/send-proposal`, { method: "POST" }), "Proposta enviada ao cliente.")}>Enviar</Btn>
                </div>
              </div>
            ))}
            <Btn tone="ghost" className="mt-2" onClick={() => run(() => api("/v1/opportunities", { method: "POST", json: { lead_id: id, plan: "basic" } }), "Oportunidade criada (plano básico).")}>
              + Nova oportunidade
            </Btn>
          </Card>
        </div>
      </div>
    </>
  );
}
