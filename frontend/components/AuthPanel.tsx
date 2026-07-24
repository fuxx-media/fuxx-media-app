"use client";

import { FormEvent, useEffect, useState } from "react";
import { fetchCurrentUser, login, logout, readCsrfCookie } from "@/lib/api";
import type { AuthenticatedUser } from "@/types/system";
import { CaseWorkspace } from "@/components/CaseWorkspace";
import { ProviderWorkspace } from "@/components/ProviderWorkspace";
import { MediaWorkspace } from "@/components/MediaWorkspace";

export function AuthPanel() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [tenant, setTenant] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("Session wird geprüft …");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void fetchCurrentUser()
      .then((current) => {
        setUser(current);
        setMessage("Serverseitige Session aktiv");
      })
      .catch(() => setMessage("Nicht angemeldet"));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      const authenticated = await login({ tenant_slug: tenant, email, password });
      setUser(authenticated);
      setPassword("");
      setMessage("Login erfolgreich");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Login fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  }

  async function endSession() {
    const csrf = readCsrfCookie();
    if (!csrf) {
      setMessage("CSRF-Cookie fehlt");
      return;
    }
    setBusy(true);
    try {
      await logout(csrf);
      setUser(null);
      setMessage("Session widerrufen");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Logout fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="auth-panel" aria-labelledby="auth-title">
        <div>
          <p className="eyebrow">Zugriffsschutz</p>
          <h2 id="auth-title">Serverseitige Session</h2>
          <p className="auth-message" role="status">
            {message}
          </p>
        </div>
        {user ? (
          <div className="session-card">
            <strong>{user.email}</strong>
            <span>{user.roles.join(", ")}</span>
            <button disabled={busy} onClick={() => void endSession()} type="button">
              Abmelden
            </button>
          </div>
        ) : (
          <form className="login-form" onSubmit={(event) => void submit(event)}>
            <label>
              Mandant
              <input required value={tenant} onChange={(event) => setTenant(event.target.value)} />
            </label>
            <label>
              E-Mail
              <input
                autoComplete="username"
                required
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <label>
              Passwort
              <input
                autoComplete="current-password"
                minLength={12}
                required
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <button disabled={busy} type="submit">
              Anmelden
            </button>
          </form>
        )}
      </section>
      {user ? <MediaWorkspace user={user} /> : null}
      {user ? <ProviderWorkspace user={user} /> : null}
      {user ? <CaseWorkspace user={user} /> : null}
    </>
  );
}
