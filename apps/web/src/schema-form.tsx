import { useId, useState } from "react";
import { Button } from "./components/ui/button";
export type Value = string | number | boolean | null | Value[] | { [key: string]: Value };
export type Schema = { $ref?: string; $defs?: Record<string, Schema>; title?: string; type?: string; enum?: Value[]; const?: Value; default?: Value; anyOf?: Schema[]; properties?: Record<string, Schema>; additionalProperties?: Schema | boolean; items?: Schema; required?: string[]; minimum?: number; maximum?: number };
function resolved(schema: Schema, root: Schema): Schema {
  if (schema.$ref) return resolved(root.$defs![schema.$ref.split("/").at(-1)!], root);
  if (schema.anyOf) return resolved(schema.anyOf.find(v => v.type !== "null")!, root);
  return schema;
}
function initial(schema: Schema, root: Schema): Value {
  const s = resolved(schema, root);
  return s.default ?? s.const ?? s.enum?.[0] ?? (s.type === "object" ? Object.fromEntries((s.required ?? []).map(k => [k, initial(s.properties![k], root)])) : s.type === "array" ? [] : s.type === "boolean" ? false : s.type === "integer" || s.type === "number" ? s.minimum ?? 0 : "");
}
export function SchemaForm({ value, schema, root = schema, onChange, label = "Household constitution" }: { value: Value; schema: Schema; root?: Schema; onChange: (v: Value) => void; label?: string }) {
  const id = useId();
  const [key, setKey] = useState("");
  const s = resolved(schema, root);
  if (s.const !== undefined) return <label>{label}<input value={String(s.const)} readOnly /></label>;
  if (s.enum) return <label htmlFor={id}>{label}<select id={id} value={String(value)} onChange={e => onChange(s.enum!.find(v => String(v) === e.target.value)!)}>{s.enum.map(v => <option key={String(v)}>{String(v)}</option>)}</select></label>;
  if (s.type === "object") {
    const data = (value && !Array.isArray(value) && typeof value === "object" ? value : {}) as Record<string, Value>;
    const props = s.properties ?? {};
    const extra = typeof s.additionalProperties === "object" ? s.additionalProperties : undefined;
    const choices = Object.keys(props).filter(k => !(k in data));
    return <fieldset><legend>{label}</legend>{Object.entries(data).map(([name, v]) => <div key={name} className="form-field"><SchemaForm schema={props[name] ?? extra ?? { type: "string" }} root={root} value={v} onChange={next => onChange({ ...data, [name]: next })} label={name.replaceAll("_", " ")} />{!s.required?.includes(name) && <Button type="button" onClick={() => { const next = { ...data }; delete next[name]; onChange(next); }}>Remove {name}</Button>}</div>)}{(choices.length > 0 || extra) && <div className="flex flex-wrap gap-2">{extra ? <label>New entry<input value={key} onChange={e => setKey(e.target.value)} /></label> : <label>Add setting<select value={key} onChange={e => setKey(e.target.value)}><option value="">Choose a setting</option>{choices.map(k => <option key={k}>{k}</option>)}</select></label>}<Button type="button" disabled={!key || key in data || (!extra && !choices.includes(key))} onClick={() => { onChange({ ...data, [key]: initial(props[key] ?? extra!, root) }); setKey(""); }}>Add</Button></div>}</fieldset>;
  }
  if (s.type === "array") {
    const values = Array.isArray(value) ? value : [];
    return <fieldset><legend>{label}</legend>{values.map((v, i) => <div key={i}><SchemaForm schema={s.items!} root={root} value={v} label={`${label} ${i + 1}`} onChange={next => onChange(values.map((old, j) => i === j ? next : old))} /><Button type="button" onClick={() => onChange(values.filter((_, j) => i !== j))}>Remove entry {i + 1}</Button></div>)}<Button type="button" onClick={() => onChange([...values, initial(s.items!, root)])}>Add entry</Button></fieldset>;
  }
  if (s.type === "boolean") return <label htmlFor={id}><input id={id} type="checkbox" checked={value === true} onChange={e => onChange(e.target.checked)} /> {label}</label>;
  const numeric = s.type === "number" || s.type === "integer";
  return <label htmlFor={id}>{label}<input id={id} type={numeric ? "number" : "text"} step={s.type === "integer" ? 1 : "any"} min={s.minimum} max={s.maximum} value={String(value ?? "")} onChange={e => onChange(numeric ? Number(e.target.value) : e.target.value)} /></label>;
}
