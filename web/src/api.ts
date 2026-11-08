import { useCallback, useEffect, useState } from "react";

// Token em sessionStorage: some ao fechar a aba. Risco de XSS mitigado por CSP estrita no nginx.
const KEY = "pp_token";
export const getToken = (): string | null => sessionStorage.getItem(KEY);
export const setToken = (t: string | null): void => {
  if (t) sessionStorage.setItem(KEY, t);
  else sessionStorage.removeItem(KEY);
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Init = Omit<RequestInit, "body"> & { json?: unknown };

export async function api<T = any>(path: string, init: Init = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body: string | undefined;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const res = await fetch(path, { ...init, headers, body });
  if (res.status === 401 && token) {
    setToken(null);
    window.location.href = "/login";
    throw new ApiError(401, "Sessão expirada");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* corpo sem JSON */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function useApi<T = any>(path: string | null, refreshMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    api<T>(path)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [path, tick]);

  useEffect(() => {
    if (!refreshMs) return;
    const id = setInterval(reload, refreshMs);
    return () => clearInterval(id);
  }, [refreshMs, reload]);

  return { data, error, loading, reload };
}
