import { ReactNode } from "react";

export function Card({ q, title, children, full }: { q?: string; title?: string; children: ReactNode; full?: boolean }) {
  return (
    <div className={"card" + (full ? " full" : "")}>
      {title && <h3>{title}</h3>}
      {q && <p className="q">{q}</p>}
      {children}
    </div>
  );
}

export function Stat({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div className="stat">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}

export function Traffic({ level, label }: { level?: string; label?: string }) {
  const lv = (level || "low").toLowerCase();
  return (
    <span className="pill">
      <span className={"dot " + lv} /> {label || lv.toUpperCase()}
    </span>
  );
}

export function Why({ children, text }: { children: ReactNode; text: string }) {
  return (
    <span className="why" title={text}>
      {children}
    </span>
  );
}

export function Learn({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="learn">
      <summary>{title}</summary>
      <p>{children}</p>
    </details>
  );
}

export function Provenance({ p }: { p?: any }) {
  if (!p) return null;
  const mode = p.mode || "derived";
  const cls = mode === "live" ? "live" : mode === "demo" ? "demo" : "";
  const ts = p.timestamp ? new Date(p.timestamp).toLocaleString("en-IN") : "—";
  return (
    <span className={"chip " + cls} title={`source ${p.source} • forward ${p.forward_source} • ${p.engine_version}`}>
      {mode.toUpperCase()} · as of {ts}
    </span>
  );
}
