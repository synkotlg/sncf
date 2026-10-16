const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
const num = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

export function money(v: number | null | undefined, currency = "EUR"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (currency !== "EUR") return `${num.format(v)} ${currency}`;
  return eur.format(v);
}

export function moneyShort(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 10000) return `${num.format(v / 1000)} k€`;
  return `${Math.round(v)} €`;
}

export function number(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return num.format(v);
}

export function date(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return iso;
  return `${d}/${m}/${y}`;
}

export function monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const names = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  return `${names[(m || 1) - 1]} ${y}`;
}

export function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v * 100)} %`;
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} Ko`;
  return `${num.format(n / 1024 / 1024)} Mo`;
}
