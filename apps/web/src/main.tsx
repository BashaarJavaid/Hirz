import { useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, passkey, useResource } from "./api";
import { AsyncButton, Load, Secret } from "./components/primitives";
import { Button } from "./components/ui/button";
import { Tonight } from "./pages/Tonight";
import { Approvals } from "./pages/Approvals";
import { ConstitutionPage } from "./pages/Constitution";
import { Household } from "./pages/Household";
import { Audit } from "./pages/Audit";
import { Twin } from "./pages/Twin";
import type { Session } from "./types";
import "./style.css";
import { Simulator } from "./simulator";

function Login({ refresh }: { refresh: () => void }) {
  const [token, setToken] = useState(""), [secret, setSecret] = useState("");
  return <main className="login">
    <p className="wordmark">Hirz</p>
    <h1>Your household, your rules.</h1>
    <p>Sign in with your own passkey to review rules and respond to requests.</p>
    {secret ? <>
      <Secret value={secret} />
      <Button variant="default" onClick={refresh}>I saved my recovery code</Button>
    </> : <>
      <AsyncButton
        primary
        run={async () => {
          await passkey({ operation: "login" });
          refresh();
        }}
      >
        Sign in with a passkey
      </AsyncButton>
      <details>
        <summary>Set up a passkey or recover access</summary>
        <label>
          Invitation or one-time recovery code
          <input autoComplete="off" type="password" value={token} onChange={e => setToken(e.target.value)} />
        </label>
        <AsyncButton
          disabled={!token}
          run={async () => {
            const result = await passkey({ operation: "enroll", token });
            setToken("");
            if (result.recovery_code) setSecret(result.recovery_code);
            else refresh();
          }}
        >
          Enroll a passkey
        </AsyncButton>
      </details>
      <p className="muted">
        Owners need a remaining passkey or recovery code to recover access. Local setup cannot reset an enrolled member.
      </p>
    </>}
  </main>;
}

function Shell({ session, refresh }: { session: Session; refresh: () => void }) {
  const location = useLocation();
  return <div className="shell">
    <a className="skip" href="#main">Skip to content</a>
    <aside>
      <NavLink to="/tonight" className="wordmark">Hirz</NavLink>
      <p className="muted">{session.member?.display_name}’s household</p>
      <nav aria-label="Main">
        {["tonight", "approvals", "constitution", "household", "audit", "twin"].map(page => <NavLink
          key={page}
          to={`/${page}`}
        >
          {page[0].toUpperCase() + page.slice(1)}
        </NavLink>)}
      </nav>
      <AsyncButton
        run={async () => {
          await api("/auth/logout", {});
          refresh();
        }}
      >
        Sign out
      </AsyncButton>
    </aside>
    <main id="main" tabIndex={-1} key={location.pathname}>
      <Routes>
        <Route path="/tonight" element={<Tonight />} />
        <Route path="/constitution" element={<ConstitutionPage />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/household" element={<Household />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/twin" element={<Twin />} />
        <Route path="*" element={<Navigate replace to="/tonight" />} />
      </Routes>
    </main>
  </div>;
}

function CompanionApp() {
  const session = useResource<Session>("/auth/session");
  if (!session.data || session.error) return <main className="login"><Load {...session} /></main>;
  return session.data.authenticated
    ? <Shell session={session.data} refresh={session.retry} />
    : <Login refresh={session.retry} />;
}

function App() {
  return useLocation().pathname === "/simulator" ? <Simulator /> : <CompanionApp />;
}
createRoot(document.getElementById("root")!).render(<BrowserRouter><App /></BrowserRouter>);
