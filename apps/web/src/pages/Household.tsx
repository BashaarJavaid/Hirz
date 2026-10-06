import { useState } from "react";
import { api, passkey, useResource } from "../api";
import { AsyncButton, Load, Panel, Secret } from "../components/primitives";
import type { Value } from "../schema-form";
import { date } from "../types";

export function Household() {
  const r = useResource<{
    graph: Record<string, Record<string, Value>[]>;
    credentials: { credential_id: string; label: string; revoked_at: string | null; member_id: string }[];
  }>("/household");
  const [secret, setSecret] = useState(""), [lockout, setLockout] = useState(false);
  if (!r.data || r.error) return <Load {...r} />;
  return <>
    <h1>Household</h1>
    {secret && <Secret value={secret} />}
    <Panel title="Passkeys">
      <p>Add a second distinct credential, especially for the owner. Passkeys may sync across devices.</p>
      <AsyncButton
        run={async () => {
          await passkey({ operation: "add_credential" });
          r.retry();
        }}
      >
        Add a passkey
      </AsyncButton>
      <label>
        <input
          type="checkbox"
          checked={lockout}
          onChange={e => setLockout(e.target.checked)}
        /> I understand revoking the last passkey may lock this member out.
      </label>
      {r.data.credentials.map(k => <article key={k.credential_id}>
        <h3>{k.label}</h3>
        {k.revoked_at ? <p>Revoked {date(k.revoked_at)}</p> : <AsyncButton
          run={async () => {
            await passkey({ operation: "revoke", credential_id: k.credential_id, confirm_lockout: lockout });
            r.retry();
          }}
        >
          Revoke passkey
        </AsyncButton>}
      </article>)}
    </Panel>
    <Panel title="Members">
      {r.data.graph.members.map(m => <article key={String(m.id)}>
        <h3>{String(m.display_name)}</h3>
        <p>{String(m.role)}</p>
        {m.role !== "owner" && <AsyncButton
          run={async () => {
            const result = await passkey({ operation: "reinvite", member_id: m.id });
            setSecret(result.invitation ?? "");
          }}
        >
          Issue a new invitation
        </AsyncButton>}
      </article>)}
    </Panel>
    <Panel title="Devices">
      {r.data.graph.assets.map(a => <article key={String(a.id)}>
        <h3>{String(a.name)}</h3>
        <p>{a.managed_through_hirz === true ? "Managed through Hirz" : "Not managed"}</p>
      </article>)}
    </Panel>
    <Panel title="Schedules">
      {(r.data.graph.schedules ?? []).map(row => <p key={String(row.id)}>{String(row.name)}</p>)}
    </Panel>
    <Panel title="Trusted contacts">
      {(r.data.graph.trusted_contacts ?? []).map(row => <article key={String(row.id)}>
        <h3>{String(row.display_name ?? row.name)}</h3>
        <AsyncButton
          run={async () => {
            await api("/contacts/remove", { id: row.id });
            r.retry();
          }}
        >
          Remove contact and close pending checks
        </AsyncButton>
      </article>)}
    </Panel>
  </>;
}
