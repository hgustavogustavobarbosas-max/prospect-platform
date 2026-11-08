import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, setToken } from "../api";
import { Btn, ErrorBox } from "../ui";

export default function Login() {
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ access_token: string }>("/v1/auth/login", { method: "POST", json: { email, password } });
      setToken(r.access_token);
      nav("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border bg-white p-6 shadow">
        <h1 className="text-xl font-bold">Prospect CRM</h1>
        <ErrorBox message={error} />
        <label className="block text-sm">E-mail
          <input className="mt-1 w-full rounded-lg border p-2" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="block text-sm">Senha
          <input className="mt-1 w-full rounded-lg border p-2" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <Btn className="w-full" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</Btn>
      </form>
    </div>
  );
}
