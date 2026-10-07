import { useState } from "react";
import { passkey, useResource } from "../api";
import { Button } from "./ui/button";
import { AsyncButton, Panel } from "./primitives";

type Link = { id: string; contact_id: string; kind: string; status: string; received: boolean };
export function Contacts({ contacts, refresh }: { contacts: { id: string; name: string }[]; refresh: () => void }) {
  const r = useResource<{ links: Link[] }>("/contacts");
  const [name, setName] = useState(""), [relationship, setRelationship] = useState("");
  const [contact, setContact] = useState(contacts.length === 1 ? contacts[0].id : ""), [email, setEmail] = useState(""), [word, setWord] = useState(""), [invitation, setInvitation] = useState("");
  const [accept, setAccept] = useState(""), [phone, setPhone] = useState("");
  async function change(command: Record<string, unknown>) {
    const result = await passkey({ operation: "contact", contact: command });
    if (result.invitation) setInvitation(result.invitation);
    setEmail(""); setWord(""); refresh(); r.retry();
  }
  return <Panel title="Trusted contacts">
    <p>Only the owner can change trust. Share invitations and safe words through a channel you already know.</p>
    {invitation && <p role="status">Single-use pairing invitation, valid for 24 hours: <code>{invitation}</code></p>}
    <details><summary>Create a contact</summary>
      <label>Name<input value={name} maxLength={100} onChange={e => setName(e.target.value)} /></label>
      <label>Relationship<input value={relationship} maxLength={100} onChange={e => setRelationship(e.target.value)} /></label>
      <AsyncButton disabled={!name || !relationship} run={async () => { await change({ operation: "create", name, relationship }); setName(""); setRelationship(""); }}>Create with passkey</AsyncButton>
    </details>
    <fieldset><legend>Contact</legend>
      {contacts.length === 0 && <p>Create a contact to set up a verified channel.</p>}
      {contacts.map(c => <Button key={c.id} aria-pressed={contact === c.id} variant={contact === c.id ? "default" : "outline"} onClick={() => setContact(c.id)}>{c.name}</Button>)}
    </fieldset>
    {contact && <>
      <AsyncButton run={async () => change({ operation: "invite", contact_id: contact, method: "app" })}>Create app pairing invitation</AsyncButton>
      <label>Email address<input autoComplete="off" type="email" value={email} maxLength={254} onChange={e => setEmail(e.target.value)} /></label>
      <AsyncButton disabled={!email} run={async () => change({ operation: "invite", contact_id: contact, method: "email", value: email })}>Send mailbox confirmation</AsyncButton>
      <label>New safe word<input autoComplete="new-password" type="password" value={word} minLength={8} maxLength={128} onChange={e => setWord(e.target.value)} /></label>
      <AsyncButton disabled={word.trim().length < 8} run={async () => change({ operation: "word", contact_id: contact, value: word })}>Set or rotate safe word</AsyncButton>
      <p>Safe words support a check; they never authorize an action.</p>
      <AsyncButton run={async () => { await change({ operation: "remove", contact_id: contact }); setContact(""); }}>Remove contact and close pending checks</AsyncButton>
    </>}
    {(r.data?.links ?? []).filter(l => !l.received && l.contact_id === contact).map(l => <article key={l.id}>
      <p>{l.kind} · {l.status}</p>
      {l.status === "confirmed" && <AsyncButton run={async () => change({ operation: "confirm", contact_id: contact, reference: l.id })}>I verified the intended contact out of band — activate</AsyncButton>}
      {l.status !== "revoked" && <AsyncButton run={async () => change({ operation: "revoke", contact_id: contact, reference: l.id })}>Revoke this {l.kind} channel</AsyncButton>}
    </article>)}
    <details><summary>Accept an app pairing invitation</summary>
      <p>Stay signed into your own household. Accept only an invitation shared by someone you know.</p>
      <label>Invitation<input autoComplete="off" type="password" value={accept} onChange={e => setAccept(e.target.value)} /></label>
      <AsyncButton disabled={!accept} run={async () => { await change({ operation: "accept", value: accept }); setAccept(""); }}>Accept with my passkey</AsyncButton>
    </details>
    {(r.data?.links ?? []).filter(l => l.received && l.status !== "revoked").map(l => <article key={l.id}>
      <p>App link · {l.status}. This grants no login to the other household.</p>
      <label>Your contact number<input type="tel" autoComplete="off" value={phone} onChange={e => setPhone(e.target.value)} /></label>
      <p>This is contact-confirmed; it does not prove phone possession.</p>
      <AsyncButton disabled={!phone} run={async () => { await change({ operation: "phone", reference: l.id, value: phone }); setPhone(""); }}>Confirm my number</AsyncButton>
      <AsyncButton run={async () => change({ operation: "withdraw", reference: l.id })}>Withdraw this app link</AsyncButton>
    </article>)}
    {r.error && <p role="alert">{r.error}</p>}
  </Panel>;
}
