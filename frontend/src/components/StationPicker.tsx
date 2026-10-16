import { useEffect, useRef, useState } from "react";
import { api, qs } from "../api";
import type { StationCandidate } from "../types";

interface Props {
  value?: { id: string; name: string } | null;
  placeholder?: string;
  onSelect: (s: StationCandidate | null) => void;
  autoFocus?: boolean;
  ariaLabel?: string;
}

// Recherche de gare tolérante (accents, abréviations "St", noms FR/NL).
export default function StationPicker({ value, placeholder, onSelect, autoFocus, ariaLabel }: Props) {
  const [q, setQ] = useState(value?.name ?? "");
  const [items, setItems] = useState<StationCandidate[]>([]);
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => setQ(value?.name ?? ""), [value?.id, value?.name]);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!open || q.trim().length < 2) {
      setItems([]);
      return;
    }
    timer.current = window.setTimeout(() => {
      api
        .get<{ results: StationCandidate[] }>(`/api/reference/stations/search${qs({ q: q.trim(), limit: 8 })}`)
        .then((r) => {
          setItems(r.results);
          setHi(0);
        })
        .catch(() => setItems([]));
    }, 160);
    return () => window.clearTimeout(timer.current);
  }, [q, open]);

  const choose = (s: StationCandidate) => {
    setQ(s.name);
    setOpen(false);
    onSelect(s);
  };

  return (
    <div className="ac">
      <input
        value={q}
        placeholder={placeholder ?? "Rechercher une gare"}
        aria-label={ariaLabel ?? placeholder ?? "Gare"}
        autoFocus={autoFocus}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          if (!e.target.value) onSelect(null);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            setHi((h) => Math.min(items.length - 1, h + 1));
            e.preventDefault();
          } else if (e.key === "ArrowUp") {
            setHi((h) => Math.max(0, h - 1));
            e.preventDefault();
          } else if (e.key === "Enter" && items[hi]) {
            choose(items[hi]);
            e.preventDefault();
          } else if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && items.length > 0 && (
        <div className="ac-list" role="listbox">
          {items.map((s, i) => (
            <div key={s.id} className={`ac-item ${i === hi ? "on" : ""}`} onMouseDown={() => choose(s)} role="option" aria-selected={i === hi}>
              <span>
                {s.name}
                {s.matched_alias && <span className="ac-sub"> · {s.matched_alias}</span>}
              </span>
              <span className="ac-sub">{s.country ?? ""}{s.uic ? ` · UIC ${s.uic}` : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
