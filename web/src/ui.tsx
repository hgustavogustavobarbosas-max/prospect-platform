import type { ButtonHTMLAttributes, ReactNode } from "react";

export const fmtBRL = (cents: number | null | undefined): string =>
  cents == null ? "sob consulta" : (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
export const fmtUSD = (micro: number | null | undefined): string =>
  micro == null ? "-" : (micro / 1_000_000).toLocaleString("en-US", { style: "currency", currency: "USD" });
export const fmtDate = (iso?: string | null): string => (iso ? new Date(iso).toLocaleString("pt-BR") : "-");
export const pct = (v: number | null | undefined): string => (v == null ? "-" : `${Math.round(v * 100)}%`);

export function Card({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      {title && <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card>
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-bold">{value}</div>
      {hint && <div className="text-xs text-slate-400">{hint}</div>}
    </Card>
  );
}

const TONES: Record<string, string> = {
  A: "bg-emerald-100 text-emerald-800", B: "bg-sky-100 text-sky-800", C: "bg-slate-100 text-slate-600",
  critical: "bg-red-100 text-red-800", warning: "bg-amber-100 text-amber-800", info: "bg-slate-100 text-slate-600",
  won: "bg-emerald-100 text-emerald-800", lost: "bg-slate-200 text-slate-600", handoff: "bg-amber-100 text-amber-800",
  suppressed: "bg-red-100 text-red-800",
};
export function Badge({ text, tone }: { text: string | null | undefined; tone?: string }) {
  const t = text ?? "-";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone ?? t] ?? "bg-blue-100 text-blue-800"}`}>{t}</span>;
}

export function Btn(props: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "primary" | "ghost" | "danger" }) {
  const { tone = "primary", className = "", ...rest } = props;
  const style =
    tone === "primary" ? "bg-blue-700 text-white hover:bg-blue-800"
    : tone === "danger" ? "bg-red-600 text-white hover:bg-red-700"
    : "border border-slate-300 bg-white hover:bg-slate-50";
  return <button {...rest} className={`rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${style} ${className}`} />;
}

export function ErrorBox({ message }: { message: string | null }) {
  return message ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{message}</div> : null;
}
export const Loading = () => <div className="p-6 text-sm text-slate-500">Carregando…</div>;
