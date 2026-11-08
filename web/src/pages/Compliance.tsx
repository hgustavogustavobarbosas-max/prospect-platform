import { FormEvent, useState } from "react";
import { api, useApi } from "../api";
import { Badge, Btn, Card, ErrorBox, Loading, fmtDate } from "../ui";

export default function Compliance() {
  const sup = useApi<any[]>("/v1/suppression?limit=100");
  const [ident, setIdent] = useState("");
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  async function check(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      setResult(await api(`/v1/compliance/can-contact?identifier=${encodeURIComponent(ident)}&channel=whatsapp`));
    } catch (x) {
      setErr((x as Error).message);
    }
  }
  async function suppress() {
    setErr(null);
    try {
      await api("/v1/suppression", { method: "POST", json: { identifier: ident, reason: "manual", source: "crm" } });
      sup.reload();
    } catch (x) {
      setErr((x as Error).message);
    }
  }
  async function exportData() {
    setErr(null);
    try {
      const d = await api<any>(`/v1/privacy/export?identifier=${encodeURIComponent(ident)}`);
      setResult(d);
    } catch (x) {
      setErr((x as Error).message);
    }
  }
  async function erase() {
    if (!window.confirm("Apagar/anonimizar TODOS os dados deste titular? Esta ação não pode ser desfeita.")) return;
    setErr(null);
    try {
      setResult(await api("/v1/privacy/erase", { method: "POST", json: { identifier: ident, confirm: true } }));
    } catch (x) {
      setErr((x as Error).message);
    }
  }

  return (
    <>
      <h1 className="text-xl font-bold">Conformidade (LGPD)</h1>
      <ErrorBox message={err} />
      <Card title="Consultar / agir sobre um telefone ou e-mail">
        <form onSubmit={check} className="flex flex-wrap gap-2">
          <input className="min-w-[16rem] flex-1 rounded-lg border p-2 text-sm" placeholder="(11) 91234-5678 ou email@exemplo.com" value={ident} onChange={(e) => setIdent(e.target.value)} required />
          <Btn>Posso contatar?</Btn>
          <Btn type="button" tone="ghost" onClick={suppress}>Suprimir</Btn>
          <Btn type="button" tone="ghost" onClick={exportData}>Exportar dados (admin)</Btn>
          <Btn type="button" tone="danger" onClick={erase}>Apagar dados (admin)</Btn>
        </form>
        {result && <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-slate-50 p-3 text-xs">{JSON.stringify(result, null, 2)}</pre>}
      </Card>
      <Card title="Lista de supressão (ninguém aqui recebe contato)">
        {sup.loading ? <Loading /> : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500"><tr><th className="p-2">Identificador</th><th>Motivo</th><th>Origem</th><th>Desde</th></tr></thead>
            <tbody>
              {sup.data?.map((s) => (
                <tr key={s.id} className="border-t"><td className="p-2">{s.identifier}</td><td><Badge text={s.reason} tone="info" /></td><td>{s.source}</td><td>{fmtDate(s.created_at)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
