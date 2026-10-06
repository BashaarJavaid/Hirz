import { useEffect, useRef, useState } from "react";
import { McpAppFrame, Transcript, useVoice } from "addon-host";
import type { TranscriptEvent } from "addon-host";
import "addon-host/style.css";
import { api } from "./api";
import { Button } from "./components/ui/button";
import type { Schema, Value } from "./schema-form";
import { SchemaForm } from "./schema-form";
import "./simulator.css";

type Prompt = { id: string; message: string; schema: Schema; kind: string };
type Session = { csrf: string; account: string; accounts: Record<string, string>; model: string; models: Record<string, string>; linked: boolean; generation: number; prompt: Prompt | null; busy: boolean };
type Event = { id: string; generation: number; kind: string; replay?: boolean; text?: string; tool?: string; elapsed_ms?: number; waiting_ms?: number; processing_ms?: number; prompt_latency_ms?: number; status?: string; prompt?: Prompt; card?: string; arguments?: Record<string, unknown>; result?: NonNullable<TranscriptEvent["result"]> };
let csrf = "";
async function request<T>(body?: Record<string, unknown>): Promise<T> {
  const r = await fetch(`/api/simulator/${body ? "command" : "session"}`, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json", "X-Hirz-Simulator-CSRF": csrf }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(r.status === 404 ? "Launch the local simulator to enable this route." : "Request refused. Check linking and the current prompt, then try again.");
  const result = await r.json(); if (result.csrf) csrf = result.csrf; return result as T;
}

function Card({ event, theme }: { event: Event; theme: "light" | "dark" }) {
  return <McpAppFrame key={event.id} url={`/api/simulator/cards/${event.card}`} args={event.arguments} result={event.result} theme={theme} title="Hirz MCP App card" name="Hirz Simulator" callTool={async params => {
    const result = await request<{ result: NonNullable<TranscriptEvent["result"]> }>({ operation: "card", tool: params.name, arguments: params.arguments ?? {}, text: "Card request" });
    return result.result;
  }} />;
}

function PromptForm({ prompt, submit }: { prompt: Prompt; submit: (body: Record<string, unknown>) => Promise<void> }) {
  const [value, setValue] = useState<Value>(() => Object.fromEntries(Object.entries(prompt.schema.properties ?? {}).filter(([key, schema]) => prompt.schema.required?.includes(key) || schema.default !== undefined).map(([key, schema]) => [key, schema.default ?? (schema.type === "boolean" ? false : "")])));
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  return <div className="panel sim-prompt" ref={ref} tabIndex={-1} role="region" aria-label="Pending question"><h2>{prompt.kind === "commitment" ? "Review this request" : "A few details"}</h2><p>{prompt.message}</p><form onSubmit={e => { e.preventDefault(); void submit({ operation: "answer", prompt_id: prompt.id, action: "accept", content: value }); }}><SchemaForm label="Your response" schema={prompt.schema} value={value} onChange={setValue} /><div className="sim-controls"><Button type="submit">Send response</Button>{["decline", "cancel"].map(action => <Button key={action} type="button" onClick={() => void submit({ operation: "answer", prompt_id: prompt.id, action })}>{action}</Button>)}</div></form></div>;
}

type Playback = { selected: string; playing: boolean; speed: number; controllable?: string[]; scenarios: Record<string, { at: string; next: number; total: number; beat: { event: string; text?: string; member?: string; response?: string; deferred?: string } | null }> };
function PlaybackControls({ choose }: { choose: (text: string) => void }) {
  const [state, setState] = useState<Playback>(), [error, setError] = useState("");
  const load = async () => { await api("/auth/session"); setState(await api<Playback>("/simulator/scenarios")); };
  useEffect(() => { void load().catch(() => {}); const timer = setInterval(() => void load().catch(() => {}), 2000); return () => clearInterval(timer); }, []);
  async function control(operation: string, scenario = state?.selected, extra: Record<string, unknown> = {}) {
    try { setError(""); await api("/simulator/scenarios", { scenario, operation, ...extra }); await load(); } catch (e) { setError(e instanceof Error ? e.message : "Playback could not continue. Refresh and try again."); }
  }
  const beat = state?.scenarios[state.selected].beat;
  return <section className="panel"><h2>Scenario playback</h2>{!state ? <p>Sign into the companion app to control your household’s scenario. Enrollment and seed-policy activation are required.</p> : <><label>Scenario<select value={state.selected} onChange={e => void control("select", e.target.value)}>{Object.keys(state.scenarios).map(name => <option key={name}>{name}</option>)}</select></label><p>{state.scenarios[state.selected].at} · event {state.scenarios[state.selected].next}/{state.scenarios[state.selected].total} · {state.playing ? "playing" : "paused"}</p><div className="sim-controls"><Button onClick={() => void control("next")}>Next event</Button>{[1, 60].map(speed => <Button key={speed} onClick={() => void control("play", state.selected, { speed })}>Play {speed}×</Button>)}<Button onClick={() => void control("pause")}>Pause</Button></div>{beat && <><p>{beat.event} {beat.member ? `· ${beat.member}’s linked Echo` : ""}</p>{beat.text && <Button onClick={() => choose(beat.text!)}>{beat.text}</Button>}{beat.response && <Button onClick={() => choose(beat.response!)}>{beat.response}</Button>}{beat.deferred && <p>Deferred: {beat.deferred}</p>}{beat.event === "constitution.activate" && <p>Review the matching proposal and activate its recorded patch in the companion app.</p>}{beat.event === "app.approve" && <p>Approve the door request with your passkey in the companion app. Then continue to verify the bounded relock.</p>}{beat.event === "contact.checkin_reply" && <><p>Choose an explicitly simulated contact reply. No real message is delivered.</p>{["genuine", "not_genuine", "will_call", "no_answer"].map(reply => <Button key={reply} onClick={() => void control("reply", state.selected, { reply })}>{reply.replaceAll("_", " ")}</Button>)}</>}</>}</>}{error && <p role="alert">{error}</p>}</section>;
}

export function Simulator() {
  const [session, setSession] = useState<Session>(), [error, setError] = useState(""), [events, setEvents] = useState<Event[]>([]), [text, setText] = useState(""), [mode, setMode] = useState("show"), [theme, setTheme] = useState<"light" | "dark">("dark"), [voice, setVoice] = useState(false), [prompt, setPrompt] = useState<Prompt | null>(null), [card, setCard] = useState<Event>();
  const input = useRef<HTMLInputElement>(null);
  const choose = (value: string) => { setText(value); input.current?.focus(); input.current?.scrollIntoView({ block: "center" }); };
  const sessionRef = useRef<Session | undefined>(undefined), voiceRef = useRef(false);
  const { listening, listen, stop, speak } = useVoice({ onText: receivedSpeech, onError: setError });
  const load = async () => { const s = await request<Session>(); sessionRef.current = s; setSession(s); setPrompt(s.prompt); };
  const submitRef = useRef<(body: Record<string, unknown>) => Promise<void>>(async () => {});
  submitRef.current = async body => {
    setError("");
    try {
      if (["account", "model", "cancel"].includes(String(body.operation))) { stop(); setCard(undefined); setPrompt(null); setEvents([]); }
      const result = await request<{ url?: string }>(body);
      if (result.url) { window.location.assign(result.url); return; }
      await load();
    } catch (e) { setError(String(e)); }
  };
  const [submit] = useState(() => (body: Record<string, unknown>) => submitRef.current(body));
  useEffect(() => { void load().catch(e => setError(String(e))); return stop; }, []);
  useEffect(() => {
    if (!session) return;
    setEvents([]); setCard(undefined);
    const stream = new EventSource("/api/simulator/events");
    const seen = new Set<string>();
    let interruption: ReturnType<typeof setTimeout>;
    stream.onopen = () => { clearTimeout(interruption); setError(""); };
    stream.onmessage = message => {
      const event = JSON.parse(message.data) as Event;
      if (seen.has(event.id)) return; seen.add(event.id);
      setEvents(old => [...old.slice(-199), event]);
      if (event.generation !== sessionRef.current?.generation) return;
      if (event.kind === "prompt") setPrompt(event.prompt ?? null);
      if (event.kind === "wait" || event.kind === "settled") { setPrompt(null); void load().catch(() => {}); }
      if (event.card && event.result) setCard(event);
      if ((event.kind === "speech" || event.kind === "prompt") && !event.replay && voiceRef.current && "speechSynthesis" in window) {
        speak(event.text ?? event.prompt?.message ?? "");
      }
    };
    stream.onerror = () => { clearTimeout(interruption); interruption = setTimeout(() => setError("Event stream interrupted. Accepted requests may still finish; refresh to reconcile."), 5000); };
    return () => { clearTimeout(interruption); stream.close(); };
  }, [session?.account, session?.generation]); // Account and generation are the stream identity.
  function receivedSpeech(final: string) {
      setText(final);
      if (!prompt) { void submit({ operation: "turn", text: final }); return; }
      const normalized = final.toLowerCase().replace(/[.!?]/g, "").trim();
      if (["cancel", "decline", "no"].includes(normalized)) { void submit({ operation: "answer", prompt_id: prompt.id, action: normalized === "cancel" ? "cancel" : "decline" }); return; }
      const properties = Object.entries(prompt.schema.properties ?? {});
      if (properties.length !== 1) { setError("Please use the response form for these details."); return; }
      const [key, schema] = properties[0];
      const value = schema.type === "boolean" ? ["yes", "confirm", "yes confirm"].includes(normalized) : ["integer", "number"].includes(schema.type ?? "") ? Number(normalized) : final;
      if (schema.type === "boolean" && value !== true || typeof value === "number" && !Number.isFinite(value)) { setError("Say yes, no, or the requested value. You can also use the response form."); return; }
      void submit({ operation: "answer", prompt_id: prompt.id, action: "accept", content: { [key]: value } });
  }
  return <main className={`simulator ${theme}`} tabIndex={-1}><header><a href="/tonight" className="wordmark">Hirz</a><h1>Household simulator</h1><p className="sim-honesty">Emulated Alexa+ host · {session?.models[session.model] ?? "Scripted"} · Simulated devices and contact replies</p></header>{error && <p role="alert">{error}</p>}{session && <><div className="sim-controls"><label>Echo account<select value={session.account} onChange={e => void submit({ operation: "account", text: e.target.value })}>{Object.entries(session.accounts).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>Host<select value={session.model} onChange={e => void submit({ operation: "model", text: e.target.value })}>{Object.entries(session.models).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>Display<select value={mode} onChange={e => { stop(); setMode(e.target.value); }}><option value="show">Echo Show</option><option value="dot">Echo Dot · voice only</option></select></label><label>Theme<select value={theme} onChange={e => setTheme(e.target.value as "light" | "dark")}><option>dark</option><option>light</option></select></label><Button onClick={() => void submit({ operation: "link" })}>{session.linked ? "Relink Echo" : "Link Echo with consent"}</Button></div><p>Rule activation and security approval finish in your <a href="/constitution" target="_blank" rel="noreferrer">companion app</a> under its own household login.</p><PlaybackControls choose={choose} /><div className="sim-layout"><section aria-label="Echo"><div className="sim-display">{mode === "show" && card ? <Card event={card} theme={theme} /> : <div className="sim-empty"><div className="sim-orb" aria-hidden="true" /><h2>{session.accounts[session.account]}</h2><p>{mode === "dot" ? "Voice-only mode. No card is mounted." : "Your household’s next response appears here."}</p></div>}</div>{prompt && <PromptForm key={prompt.id} prompt={prompt} submit={submit} />}<form onSubmit={e => { e.preventDefault(); void submit({ operation: "turn", text }); setText(""); }}><label>Your request<input ref={input} value={text} onChange={e => setText(e.target.value)} maxLength={2000} /></label><div className="sim-controls"><Button type="submit" disabled={!session.linked || session.busy || !text.trim()}>Send</Button><Button type="button" onClick={listen} disabled={!session.linked}>{listening ? "Finish listening" : "Push to talk"}</Button><Button type="button" onClick={() => void submit({ operation: "cancel" })}>Cancel turn</Button><label><input type="checkbox" checked={voice} onChange={e => { setVoice(e.target.checked); voiceRef.current = e.target.checked; if (!e.target.checked) stop(); }} /> Speak responses</label></div></form><details><summary>Recorded utterances</summary>{["What can you do?", "What's going on tonight?", "From now on, never unlock the door for someone we're not expecting.", "Do it.", "Let them in.", "Malik just called from a strange number. He says he's in trouble and needs five hundred dollars. Is it really him?", "Alexa, is it him?"].map(line => <Button key={line} onClick={() => choose(line)}>{line}</Button>)}</details></section><Transcript events={events} /></div></>}</main>;
}
