import { useState } from "react";
import { useResource } from "../api";
import { Load } from "../components/primitives";
import { Button } from "../components/ui/button";
import type { Value } from "../schema-form";
import { date } from "../types";

export function Audit() {
  const [event, setEvent] = useState(""), [before, setBefore] = useState<number>();
  const r = useResource<{
    rows: { seq: number; event_type: string; created_at: string; payload: Value; curr_hash: string }[];
    anchoring: string;
  }>(`/audit?event=${encodeURIComponent(event)}${before === undefined ? "" : `&before=${before}`}`);
  return <>
    <h1>Audit</h1>
    <p>The household’s signed record.</p>
    <label>
      Filter by event
      <select
        value={event}
        onChange={e => {
          setEvent(e.target.value);
          setBefore(undefined);
        }}
      >
        {["", "CONSTITUTION_ACTIVATED", "APPROVED", "EXECUTED", "VERIFIED", "DENY_CONSTITUTION"].map(v => <option
          key={v}
          value={v}
        >
          {v || "All events"}
        </option>)}
      </select>
    </label>
    <Button asChild><a href="/api/audit/export">Verify and download signed export</a></Button>
    {!r.data || r.error ? <Load {...r} /> : <>
      <p className="muted">{r.data.anchoring}</p>
      {r.data.rows.map(row => <details className="panel" key={row.seq}>
        <summary>{row.event_type.replaceAll("_", " ")} · {date(row.created_at)}</summary>
        <p>Sequence {row.seq}</p>
        <pre>{JSON.stringify(row.payload, null, 2)}</pre>
        <p className="hash">{row.curr_hash}</p>
      </details>)}
      <div className="flex gap-2">
        {before !== undefined && <Button onClick={() => setBefore(undefined)}>Latest events</Button>}
        {r.data.rows.length === 100 && <Button onClick={() => setBefore(r.data!.rows.at(-1)!.seq)}>
          Older events
        </Button>}
      </div>
    </>}
  </>;
}
