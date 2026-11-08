import { useState } from "react";
import { api, useApi } from "../api";
import { Btn, Card, ErrorBox, Loading, fmtBRL } from "../ui";

function Row({ plan, onSaved }: { plan: any; onSaved: () => void }) {
  const [price, setPrice] = useState(plan.price_cents != null ? String(plan.price_cents / 100) : "");
  const [desc, setDesc] = useState(plan.description ?? "");
  const [feats, setFeats] = useState((plan.features ?? []).join("\n"));
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    setErr(null);
    const cents = price.trim() === "" ? null : Math.round(parseFloat(price.replace(",", ".")) * 100);
    if (cents !== null && (Number.isNaN(cents) || cents < 0)) return setErr("Preço inválido");
    try {
      await api(`/v1/plans/${plan.id}`, {
        method: "PATCH",
        json: { price_cents: cents, description: desc, features: feats.split("\n").map((s: string) => s.trim()).filter(Boolean) },
      });
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  return (
    <Card title={`${plan.name} (${plan.code})`}>
      <ErrorBox message={err} />
      <div className="grid gap-3 md:grid-cols-3">
        <label className="text-sm">Preço (R$) — vazio = sob consulta
          <input className="mt-1 w-full rounded-lg border p-2" value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" />
        </label>
        <label className="text-sm">Descrição
          <textarea className="mt-1 w-full rounded-lg border p-2" rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} />
        </label>
        <label className="text-sm">Itens inclusos (um por linha)
          <textarea className="mt-1 w-full rounded-lg border p-2" rows={3} value={feats} onChange={(e) => setFeats(e.target.value)} />
        </label>
      </div>
      <div className="mt-3 flex items-center gap-3"><Btn onClick={save}>Salvar</Btn><span className="text-xs text-slate-500">O agente passa a citar: {fmtBRL(plan.price_cents)}</span></div>
    </Card>
  );
}

export default function Plans() {
  const { data, error, loading, reload } = useApi<any[]>("/v1/plans");
  return (
    <>
      <h1 className="text-xl font-bold">Planos e preços</h1>
      <p className="text-sm text-slate-500">O agente só cita os valores cadastrados aqui.</p>
      <ErrorBox message={error} />
      {loading ? <Loading /> : data?.map((p) => <Row key={p.id + String(p.updated_at)} plan={p} onSaved={reload} />)}
    </>
  );
}
