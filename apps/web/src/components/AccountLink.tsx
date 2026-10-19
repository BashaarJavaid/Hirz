import { useState } from "react";
import { api, passkey, useResource } from "../api";
import { finishLink, startLink, type AccountLinkState } from "../account-link";
import { AsyncButton, Load, Panel } from "./primitives";

export function AccountLink() {
  const r = useResource<AccountLinkState>("/account-link");
  if (!r.data || r.error) return <Panel title="Your connected login"><Load {...r} /></Panel>;
  if (!r.data.available || !r.data.login) return null;
  return <Panel title="Your connected login">
    {r.data.linked ? <p>Your login is linked to your household membership.</p> : <>
      <p>Sign in to your own Hirz login, then confirm the link with your passkey. This connects your login to your membership in this household.</p>
      <AsyncButton run={async () => { window.location.assign(await startLink(r.data!)); }}>Link my login</AsyncButton>
    </>}
  </Panel>;
}

export function AccountLinkReturn() {
  const [returned] = useState(() => {
    const values = new URLSearchParams(window.location.search);
    window.history.replaceState(null, "", "/account-link");
    return values;
  });
  const [complete, setComplete] = useState(false);
  return <>
    <h1>Link your login</h1>
    {complete ? <p role="status">Your login is linked to your household membership.</p> : <>
      <p>Confirm that the login you just used is yours. Your passkey will link it to your current household membership.</p>
      <AsyncButton primary run={async () => {
        const config = await api<AccountLinkState>("/account-link");
        const token = await finishLink(config, returned);
        await passkey({ operation: "link_account", account_token: token, account_binding: config.session_binding });
        setComplete(true);
      }}>Confirm with my passkey</AsyncButton>
    </>}
    <p><a href="/household">Return to Household</a></p>
  </>;
}
