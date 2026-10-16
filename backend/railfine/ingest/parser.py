"""Detection des champs d'une amende dans un texte (PDF natif ou OCR).

Principes :
- chaque valeur est accompagnee d'un indice de confiance (0-1), d'un extrait
  justificatif et des alternatives rencontrees ;
- en cas de doute (plusieurs valeurs concurrentes, contexte absent, OCR
  approximatif), le champ est marque ``uncertain`` : rien n'est invente ;
- un document peut contenir plusieurs amendes (plusieurs numeros de dossier) :
  il est alors decoupe en plusieurs brouillons.

Le texte est "replie" (minuscules, sans accents) caractere par caractere pour
garder l'alignement des positions avec le texte original.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable

UNCERTAIN_BELOW = 0.7


# --------------------------------------------------------------------------- utilitaires
def fold(text: str) -> str:
    """Minuscules sans accents, MEME LONGUEUR que le texte d'origine."""
    out = []
    for c in text:
        if c in "   \t":
            out.append(" ")
            continue
        if c in "’‘`´":
            out.append("'")
            continue
        if c in "–—−":
            out.append("-")
            continue
        d = "".join(ch for ch in unicodedata.normalize("NFKD", c) if not unicodedata.combining(ch))
        out.append((d[:1] or " ").lower() if c != "€" else "€")
    return "".join(out)


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t  ]+", " ", text)
    return text


@dataclass
class FieldValue:
    value: Any = None
    confidence: float = 0.0
    evidence: str | None = None
    alternatives: list = field(default_factory=list)
    note: str | None = None

    @property
    def uncertain(self) -> bool:
        return self.value is not None and self.confidence < UNCERTAIN_BELOW

    def to_dict(self) -> dict:
        d = asdict(self)
        d["confidence"] = round(self.confidence, 2)
        d["uncertain"] = self.uncertain
        return d


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, (len(text) if end == -1 else end)


def _evidence(text: str, start: int, end: int, pad: int = 40) -> str:
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def _context_before(folded: str, pos: int, width: int = 80) -> str:
    """Texte qui precede ``pos`` sur la meme ligne (et la fin de la ligne precedente si la ligne est courte)."""
    ls, _ = _line_bounds(folded, pos)
    ctx = folded[ls:pos]
    if len(ctx.strip()) < 4 and ls > 0:
        pls, _ = _line_bounds(folded, ls - 1)
        ctx = folded[pls : ls - 1] + " " + ctx
    return ctx[-width:]


# --------------------------------------------------------------------------- montants
AMOUNT_PATTERNS = [
    re.compile(r"(?<![\d.,])(\d{1,3}(?:[ .]\d{3})+|\d{1,5})(?:[.,](\d{1,2}))?\s?(?:€|eur\b|euros?\b)"),
    re.compile(r"(?:€|eur\b)\s?(\d{1,5})(?:[.,](\d{1,2}))?(?![\d])"),
]
AMOUNT_LABELED = re.compile(r"(?:montant|total|somme|a payer|bedrag)[^\n\d]{0,30}?(?<![\d.,])(\d{1,5})[.,](\d{2})(?![\d])")

KW_TOTAL = re.compile(r"total|montant (?:a payer|a regler|du\b|restant)|a payer|a regler|somme (?:due|a payer)|net a payer|reste a payer|te betalen|totaal")
KW_PAID = re.compile(r"\b(?:paye|payee|regle|reglee|acquitte|encaisse|verse|betaald)\b|paiement (?:recu|effectue|enregistre)|montant (?:regle|paye)|deja (?:paye|regle)|reglement de")
KW_BASE = re.compile(r"indemnite forfaitaire|amende|contravention|penalite|montant (?:initial|de base|de l'amende|de l'indemnite)|supplement|forfait|boete|toeslag|minnelijke|regularisation")
KW_FEES = re.compile(r"frais (?:de dossier|de recouvrement|d'envoi|administratifs)|frais\b")
KW_INCREASED = re.compile(r"major")
KW_TICKET = re.compile(r"prix (?:du |de )?(?:billet|titre|trajet|parcours|voyage)|tarif|billet|ritprijs|vervoerbewijs")
KW_IGNORE = re.compile(r"capital|rcs|siren|siret|tva|social|minimum|maximum|jusqu'a|plafond|par mois|heure")


def _parse_amount(intpart: str, dec: str | None) -> float | None:
    try:
        whole = int(re.sub(r"[ .]", "", intpart))
    except ValueError:
        return None
    value = whole + (int(dec.ljust(2, "0")) / 100 if dec else 0)
    return round(float(value), 2)


@dataclass
class AmountCandidate:
    value: float
    start: int
    end: int
    kinds: set


def find_amounts(text: str, folded: str) -> list[AmountCandidate]:
    seen: set[tuple[int, int]] = set()
    out: list[AmountCandidate] = []
    spans = []
    for pat in AMOUNT_PATTERNS:
        for m in pat.finditer(folded):
            spans.append((m.start(), m.end(), m.group(1), m.group(2)))
    for m in AMOUNT_LABELED.finditer(folded):
        spans.append((m.start(1), m.end(2), m.group(1), m.group(2)))
    for start, end, ip, dec in sorted(spans):
        if any(s <= start < e for s, e in seen):
            continue
        seen.add((start, end))
        v = _parse_amount(ip, dec)
        if v is None or v <= 0 or v > 5000:
            continue
        ctx = _context_before(folded, start)
        kinds = set()
        if KW_IGNORE.search(ctx):
            continue
        if KW_INCREASED.search(ctx):
            kinds.add("majore")
        if KW_PAID.search(ctx):
            kinds.add("paye")
        if KW_TOTAL.search(ctx):
            kinds.add("total")
        if KW_FEES.search(ctx):
            kinds.add("frais")
        if KW_BASE.search(ctx):
            kinds.add("base")
        if KW_TICKET.search(ctx):
            kinds.add("billet")
        out.append(AmountCandidate(v, start, end, kinds))
    return out


def extract_amounts(text: str, folded: str) -> tuple[FieldValue, FieldValue, str | None]:
    cands = find_amounts(text, folded)
    initial = FieldValue()
    paid = FieldValue()
    note = None
    if not cands:
        return initial, paid, None

    def pick(pred, conf_unique: float, conf_multi: float) -> FieldValue:
        sel = [c for c in cands if pred(c)]
        if not sel:
            return FieldValue()
        values = sorted({c.value for c in sel})
        first = sel[0]
        fv = FieldValue(first.value, conf_unique if len(values) == 1 else conf_multi, _evidence(text, first.start, first.end))
        fv.alternatives = [v for v in values if v != first.value]
        if len(values) > 1:
            fv.note = "plusieurs montants concurrents : à vérifier"
        return fv

    initial = pick(lambda c: "total" in c.kinds and "majore" not in c.kinds and "paye" not in c.kinds, 0.85, 0.55)
    if initial.value is None:
        initial = pick(lambda c: "base" in c.kinds and "majore" not in c.kinds and "frais" not in c.kinds, 0.75, 0.5)
    if initial.value is None:
        unlabeled = [c for c in cands if not c.kinds & {"paye", "majore", "billet", "frais"}]
        if unlabeled:
            values = sorted({c.value for c in unlabeled})
            c0 = unlabeled[0]
            initial = FieldValue(c0.value, 0.45 if len(values) == 1 else 0.3, _evidence(text, c0.start, c0.end),
                                 [v for v in values if v != c0.value], "montant sans libellé explicite")
    paid = pick(lambda c: "paye" in c.kinds, 0.85, 0.55)
    increased = [c for c in cands if "majore" in c.kinds]
    if increased:
        note = f"montant majoré mentionné : {increased[0].value:.2f} EUR"
    parts = []
    for label, kind in (("indemnité/amende", "base"), ("frais", "frais"), ("billet", "billet")):
        vals = sorted({c.value for c in cands if kind in c.kinds and "total" not in c.kinds})
        if vals:
            parts.append(f"{label} : " + ", ".join(f"{v:.2f}" for v in vals))
    if parts:
        initial.note = (initial.note + " ; " if initial.note else "") + "détail lu : " + " | ".join(parts)
    return initial, paid, note


# --------------------------------------------------------------------------- dates / heures
MONTHS = {
    "janvier": 1, "janv": 1, "jan": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4, "mai": 5,
    "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "octobre": 10, "oct": 10,
    "novembre": 11, "nov": 11, "decembre": 12, "dec": 12,
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}
DATE_NUM = re.compile(r"(?<![\d/.\-])(\d{1,2})\s?[/.\-]\s?(\d{1,2})\s?[/.\-]\s?(\d{4}|\d{2})(?![\d])")
DATE_TXT = re.compile(r"(?<!\d)(\d{1,2})(?:er)?\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{4})(?!\d)")
DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")

KW_DATE_POS = re.compile(
    r"date (?:de l'infraction|des faits|du controle|de constatation|de l'irregularite|du voyage|du trajet|de l'evenement)"
    r"|constatee? le|commise? le|infraction du|controle du|voyage du|trajet du|faits du|irregularite du|survenue? le"
    r"|datum (?:van )?(?:de )?(?:vaststelling|controle|overtreding)|vastgesteld op"
)
KW_DATE_NEG = re.compile(
    r"emis le|edite le|date d'emission|date d'edition|imprime le|date limite|avant le|au plus tard|echeance|delai"
    r"|nee? le|date de naissance|naissance|valable|expire|date d'envoi|courrier du|paye le|regle le|date de reglement"
    r"|date du paiement|fait a|le present|depuis le|a compter du|recu le|du \d|au \d|uiterlijk|geboren"
)
TIME_RE = re.compile(r"(?<![\d:,.])([01]?\d|2[0-3])\s?(?:h|:)\s?([0-5]\d)(?![\d])")
KW_TIME_POS = re.compile(r"heure (?:du controle|de constatation|des faits|de l'infraction)|heure|uur|tijdstip")
KW_TIME_NEG = re.compile(r"lundi|mardi|ouvert|appel|service client|joignable|horaires|du lundi|tel|telephone|accueil|depart|arrivee")


def _mk_date(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        dt = date(y, m, d)
    except ValueError:
        return None
    if dt.year < 1995 or dt > date.today().replace(year=date.today().year + 1):
        return None
    return dt


def find_dates(folded: str) -> list[tuple[date, int, int]]:
    out = []
    for m in DATE_NUM.finditer(folded):
        dt = _mk_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if dt:
            out.append((dt, m.start(), m.end()))
    for m in DATE_TXT.finditer(folded):
        dt = _mk_date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
        if dt:
            out.append((dt, m.start(), m.end()))
    for m in DATE_ISO.finditer(folded):
        dt = _mk_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            out.append((dt, m.start(), m.end()))
    out.sort(key=lambda t: t[1])
    return out


def extract_date_time(text: str, folded: str) -> tuple[FieldValue, FieldValue]:
    dates = find_dates(folded)
    times = [(m, int(m.group(1)), int(m.group(2))) for m in TIME_RE.finditer(folded)]
    scored = []
    for dt, s, e in dates:
        ctx = _context_before(folded, s, 70)
        score = 0.0
        if KW_DATE_POS.search(ctx):
            score += 3
        elif re.search(r"\bdate\b|\ble\s*$|datum", ctx):
            score += 1
        if KW_DATE_NEG.search(ctx):
            score -= 3
        after = folded[e : e + 18]
        if TIME_RE.search(after):
            score += 1.5
        if dt > date.today():
            score -= 4
        scored.append((score, s, dt, e))
    date_fv = FieldValue()
    chosen_end = None
    if scored:
        best = max(scored, key=lambda t: (t[0], -t[1]))
        distinct = sorted({t[2] for t in scored})
        if best[0] >= 3:
            conf = 0.9
        elif best[0] >= 1:
            conf = 0.7 if len(distinct) == 1 else 0.6
        else:
            conf = 0.5 if len(distinct) == 1 else 0.3
        date_fv = FieldValue(best[2].isoformat(), conf, _evidence(text, best[1], best[3]),
                             [d.isoformat() for d in distinct if d != best[2]])
        if conf < UNCERTAIN_BELOW and len(distinct) > 1:
            date_fv.note = "plusieurs dates dans le document : choisir la date du contrôle"
        chosen_end = best[3]
    time_fv = FieldValue()
    tscored = []
    for m, hh, mm in times:
        ctx = _context_before(folded, m.start(), 40)
        score = 0.0
        if KW_TIME_POS.search(ctx):
            score += 2
        if re.search(r"\ba\s*$|\bvers\s*$|\bom\s*$", ctx):
            score += 1
        if KW_TIME_NEG.search(ctx) or re.search(r"\d\s?h\s?(?:\d\d)?\s?(?:a|-)\s?$", ctx) or re.match(r"\s?(?:a|-)\s?\d{1,2}\s?h", folded[m.end():m.end() + 8]):
            score -= 3
        if chosen_end is not None and 0 <= m.start() - chosen_end <= 25:
            score += 2.5
        tscored.append((score, m, hh, mm))
    if tscored:
        best = max(tscored, key=lambda t: (t[0], -t[1].start()))
        if best[0] > 0:
            conf = 0.85 if best[0] >= 2.5 else 0.6
            others = sorted({f"{h:02d}:{mi:02d}" for sc, _m, h, mi in tscored if sc > 0} - {f"{best[2]:02d}:{best[3]:02d}"})
            time_fv = FieldValue(f"{best[2]:02d}:{best[3]:02d}", conf if not others else min(conf, 0.6),
                                 _evidence(text, best[1].start(), best[1].end()), others)
    return date_fv, time_fv


# --------------------------------------------------------------------------- gares
STOP_WORDS_STATION = r"(?=\s{2,}|\s(?:heure|train|date|n\s?[°o]|classe|le\s\d|a\s\d|\d{1,2}[h:]\d\d|prix|tarif|montant|voiture|place|depart|arrivee|via)\b|[,;|()\n]|$)"
ST_NAME = r"([a-z][a-z0-9' .\-/]{1,48}?)"
RE_ORIGIN = re.compile(r"\b(?:gare (?:de )?depart|gare d'origine|origine|provenance|depart de|au depart de|vertrekstation|vertrek|van)\b\s*[:\-]?\s+" + ST_NAME + STOP_WORDS_STATION)
RE_DEST = re.compile(r"\b(?:gare (?:d')?arrivee|gare de destination|destination|a destination de|arrivee a|aankomststation|aankomst|bestemming|naar)\b\s*[:\-]?\s+" + ST_NAME + STOP_WORDS_STATION)
RE_TRAJET = re.compile(r"\b(?:trajet|parcours|relation|itineraire|voyage|traject|reis|o/d)\b\s*[:\-]?\s*(?:de\s+|du\s+|van\s+)?" + ST_NAME +
                       r"\s+(?:a|au|vers|->|>|→|naar|tot|-|/)\s+" + ST_NAME + STOP_WORDS_STATION)
RE_ENTRE = re.compile(r"\bentre\s+(?:la gare de\s+)?" + ST_NAME + r"\s+et\s+(?:la gare de\s+)?" + ST_NAME + STOP_WORDS_STATION)
RE_ARROW = re.compile(r"^\s*" + ST_NAME + r"\s*(?:->|>|→)\s*" + ST_NAME + r"\s*$", re.M)
RE_CONTROL = re.compile(r"(?:lieu (?:du controle|de constatation|de l'infraction)|gare de controle|constatee? en gare de|controle en gare de|en gare de|plaats van controle)\s*[:\-]?\s*" + ST_NAME + STOP_WORDS_STATION)


def _clean_station(raw: str) -> str | None:
    s = re.sub(r"\s+", " ", raw).strip(" -:./'")
    s = re.sub(r"^(?:la gare de|gare de|gare d'|gare)\s+", "", s)
    if len(s) < 2 or re.fullmatch(r"[\d\s.:/-]+", s):
        return None
    if s in {"la", "le", "de", "du", "votre", "notre", "bord", "bord du train", "train"}:
        return None
    return s


def _orig(text: str, m: re.Match, g: int) -> str:
    return text[m.start(g) : m.end(g)]


def extract_stations(text: str, folded: str, mention_finder: Callable[[str], list[tuple[str, int]]] | None = None) -> dict[str, FieldValue]:
    res = {"origin_name": FieldValue(), "dest_name": FieldValue(), "control_station_name": FieldValue()}
    for pat, conf in ((RE_TRAJET, 0.8), (RE_ENTRE, 0.7), (RE_ARROW, 0.6)):
        m = pat.search(folded)
        if m:
            o, d = _clean_station(_orig(text, m, 1)), _clean_station(_orig(text, m, 2))
            if o and d and o.lower() != d.lower():
                ev = _evidence(text, m.start(), m.end(), 10)
                res["origin_name"] = FieldValue(o, conf, ev)
                res["dest_name"] = FieldValue(d, conf, ev)
                break
    if res["origin_name"].value is None:
        m = RE_ORIGIN.search(folded)
        if m and _clean_station(_orig(text, m, 1)):
            res["origin_name"] = FieldValue(_clean_station(_orig(text, m, 1)), 0.8, _evidence(text, m.start(), m.end(), 10))
    if res["dest_name"].value is None:
        m = RE_DEST.search(folded)
        if m and _clean_station(_orig(text, m, 1)):
            res["dest_name"] = FieldValue(_clean_station(_orig(text, m, 1)), 0.8, _evidence(text, m.start(), m.end(), 10))
    m = RE_CONTROL.search(folded)
    if m and _clean_station(_orig(text, m, 1)):
        res["control_station_name"] = FieldValue(_clean_station(_orig(text, m, 1)), 0.7, _evidence(text, m.start(), m.end(), 10))
    if mention_finder and (res["origin_name"].value is None or res["dest_name"].value is None):
        mentions = mention_finder(text)
        names = []
        for name, _pos in sorted(mentions, key=lambda t: t[1]):
            if name not in names:
                names.append(name)
        if res["origin_name"].value is None and res["dest_name"].value is None and len(names) == 2:
            res["origin_name"] = FieldValue(names[0], 0.4, None, note="gare repérée dans le texte sans libellé : à confirmer")
            res["dest_name"] = FieldValue(names[1], 0.4, None, note="gare repérée dans le texte sans libellé : à confirmer")
        elif names:
            for key in ("origin_name", "dest_name"):
                if res[key].value is None:
                    res[key].alternatives = names[:6]
                    res[key].note = "gares mentionnées dans le document : " + ", ".join(names[:6])
    return res


# --------------------------------------------------------------------------- train, ligne, type, transporteur
RE_TRAIN = re.compile(
    r"(?:\bn\s?[°o]\.?\s?(?:de\s)?(?:train|circulation)|\btrain|\btrein|\btgv|\bter|\bic|\bintercites?|\bouigo|\binoui|\bthalys|\beurostar|\bcirculation|\btreinnummer|\bzug)"
    r"\s*(?:n\s?[°o]\.?|no\.?|nr\.?|numero|num\.?)?\s*[:#]?\s*(\d{3,6})(?![\d/.,:])"
)
RE_RER = re.compile(r"\brer\s?([a-e])\b")
RE_LIGNE = re.compile(r"\bligne\s+(?:ter\s+|transilien\s+)?([a-z]{1,2}\d{1,3}|\d{1,3}[a-z]?|[hjklnpru])\b(?!\s?(?:de|du|des|d')\b)")
RE_SNCB_CAT = re.compile(r"\b(ic|l|p|s\d{1,2}|ice)\s?(\d{3,5})\b")

TYPE_PATTERNS = [
    ("RER", re.compile(r"\brer\b")),
    ("TRANSILIEN", re.compile(r"transilien")),
    ("TGV", re.compile(r"\btgv\b|\binoui\b|\bouigo\b|\blyria\b")),
    ("EUROSTAR", re.compile(r"\beurostar\b|\bthalys\b")),
    ("INTERCITES", re.compile(r"intercites?\b")),
    ("SNCB", re.compile(r"\bsncb\b|\bnmbs\b|belgian rail|\bb-rail")),
    ("TER", re.compile(r"\bter\b|\bfluo\b|\bmobigo\b|\baleop\b|\bbreizhgo\b|\bremi\b|\blio\b|\bzou\b|\bnomad\b|leman express")),
]

CARRIER_PATTERNS = [
    ("SNCB", re.compile(r"\bsncb\b|\bnmbs\b")),
    ("Eurostar", re.compile(r"\beurostar\b|\bthalys\b")),
    ("OUIGO (SNCF Voyageurs)", re.compile(r"\bouigo\b")),
    ("RATP", re.compile(r"\bratp\b")),
    ("SNCF Voyageurs", re.compile(r"sncf voyageurs|\bsncf\b|\bter\b|transilien|intercites|\binoui\b")),
    ("Transdev", re.compile(r"\btransdev\b")),
    ("Keolis", re.compile(r"\bkeolis\b")),
    ("Arriva", re.compile(r"\barriva\b")),
    ("Trenitalia", re.compile(r"\btrenitalia\b")),
    ("Renfe", re.compile(r"\brenfe\b")),
    ("DB", re.compile(r"deutsche bahn|\bdb fernverkehr\b")),
]
TER_REGIONS = [
    "hauts-de-france", "grand est", "normandie", "bretagne", "pays de la loire", "centre-val de loire", "nouvelle-aquitaine",
    "occitanie", "auvergne-rhone-alpes", "bourgogne-franche-comte", "provence-alpes-cote d'azur",
]


def extract_train(text: str, folded: str, station_names: list[str] | None = None) -> dict[str, FieldValue]:
    # les noms de gares ("Aeroport CDG 2 TGV", "Lyon Part Dieu TGV") ne doivent pas influencer le type de train
    for name in station_names or []:
        if name:
            fn = fold(name)
            folded = folded.replace(fn, " " * len(fn))
    res = {"train_number": FieldValue(), "line_label": FieldValue(), "train_type": FieldValue(), "carrier": FieldValue(),
           "country": FieldValue()}
    nums = []
    for m in RE_TRAIN.finditer(folded):
        n = m.group(1).lstrip("0") or m.group(1)
        if re.fullmatch(r"(19|20)\d\d", n) and re.search(r"\b(ter|tgv|ic)\s*$", folded[m.start(): m.start(1)]):
            continue  # "TER 2024" : probablement une annee
        nums.append((n, m))
    for m in RE_SNCB_CAT.finditer(folded):
        nums.append((m.group(2), m))
    if nums:
        distinct = []
        for n, _ in nums:
            if n not in distinct:
                distinct.append(n)
        n, m = nums[0]
        res["train_number"] = FieldValue(n, 0.85 if len(distinct) == 1 else 0.5, _evidence(text, m.start(), m.end(), 15), distinct[1:])
    m = RE_RER.search(folded)
    if m:
        res["line_label"] = FieldValue(f"RER {m.group(1).upper()}", 0.85, _evidence(text, m.start(), m.end(), 15))
    else:
        m = RE_LIGNE.search(folded)
        if m:
            res["line_label"] = FieldValue(f"Ligne {m.group(1).upper()}", 0.7, _evidence(text, m.start(), m.end(), 15))

    label = res["line_label"].value or ""
    if label.startswith("RER"):
        res["train_type"] = FieldValue("RER", 0.9, res["line_label"].evidence)
    found = []
    for t, pat in TYPE_PATTERNS:
        hits = list(pat.finditer(folded))
        if hits:
            found.append((t, hits))
    if found:
        # le type cite juste avant le numero de train est le plus fiable
        near_train = None
        if nums:
            pos = nums[0][1].start()
            for t, hits in found:
                if any(abs(h.start() - pos) <= 25 for h in hits):
                    near_train = t
                    break
        if res["train_type"].value is not None:
            pass
        elif near_train:
            res["train_type"] = FieldValue(near_train, 0.9, None)
        elif len(found) == 1:
            res["train_type"] = FieldValue(found[0][0], 0.75, _evidence(text, found[0][1][0].start(), found[0][1][0].end(), 20))
        else:
            ranked = sorted(found, key=lambda f: -len(f[1]))
            res["train_type"] = FieldValue(ranked[0][0], 0.45, None, [f[0] for f in ranked[1:]],
                                           "plusieurs catégories citées dans le document")
    for name, pat in CARRIER_PATTERNS:
        m = pat.search(folded)
        if m:
            label = name
            if name == "SNCF Voyageurs" and re.search(r"\bter\b", folded):
                region = next((r for r in TER_REGIONS if re.search(r"\b" + r.replace("-", "[- ]") + r"\b", folded)), None)
                if region:
                    label = f"SNCF Voyageurs - TER {region.title()}"
            res["carrier"] = FieldValue(label, 0.8, _evidence(text, m.start(), m.end(), 15))
            break
    if res["carrier"].value == "SNCB" or res["train_type"].value == "SNCB":
        res["country"] = FieldValue("BE", 0.85)
    elif res["carrier"].value and res["carrier"].value != "Eurostar":
        res["country"] = FieldValue("FR", 0.7)
    return res


# --------------------------------------------------------------------------- motif
REASON_RULES = [
    ("absence_titre", re.compile(r"absence de (?:titre|billet)|sans (?:titre|billet)|defaut de titre|pas de (?:titre|billet)|voyageur sans titre|zonder (?:geldig )?(?:vervoerbewijs|biljet|ticket)|geen (?:geldig )?(?:vervoerbewijs|biljet)"), True),
    ("non_validation", re.compile(r"non (?:composte|valide|oblitere)\b|defaut de (?:compostage|validation)|absence de (?:compostage|validation)|niet (?:gevalideerd|ontwaard)"), True),
    ("titre_non_valide", re.compile(r"(?:titre|billet)(?: de transport)? (?:non valable|invalide|perime|non conforme)|non valable (?:pour|sur|dans)|ongeldig (?:vervoerbewijs|biljet)"), True),
    ("surclassement", re.compile(r"(?:1re|1ere|premiere|1 ere) classe .{0,40}(?:2e|2eme|seconde|deuxieme)|surclassement|classe superieure|eerste klas"), True),
    ("depassement", re.compile(r"depassement de (?:parcours|trajet)|au[- ]dela de (?:la |sa )?destination|hors parcours"), True),
    ("reduction", re.compile(r"(?:carte|justificatif|reduction)[^\n]{0,40}(?:non presente|absente?|defaut|non valable|non justifie)|tarif reduit[^\n]{0,30}(?:non justifie|sans justificatif)|defaut de (?:carte|justificatif)"), False),
    ("comportement", re.compile(r"pieds? sur|\bfum(?:er|e|eur)\b|cigarette|vapot|comportement|tapage|nuisance|outrage|insulte|degradation|souill|crach"), False),
    ("refus", re.compile(r"refus (?:de|d'obtemperer)|fausse (?:adresse|identite)|refus de decliner"), False),
]
RE_REASON_LABEL = re.compile(r"(?:\bmotif|nature de l'infraction|irregularite constatee|^\s*infraction|^\s*irregularite|\breden|\bovertreding)\s*[:\-]\s*([^\n]{3,140})", re.M)


def classify_reason(text_folded: str) -> str | None:
    for code, pat, _ in REASON_RULES:
        if pat.search(text_folded):
            return code
    return None


def extract_reason(text: str, folded: str) -> tuple[FieldValue, FieldValue]:
    m = RE_REASON_LABEL.search(folded)
    if m:
        raw = re.sub(r"\s+", " ", text[m.start(1) : m.end(1)]).strip(" .:-")
        code = classify_reason(folded[m.start(1) : m.end(1)])
        return (FieldValue(code or "autre", 0.85 if code else 0.55, _evidence(text, m.start(), m.end(), 0)),
                FieldValue(raw[:140], 0.85, None))
    hits = []
    for code, pat, strong in REASON_RULES:
        if not strong:
            continue
        mm = pat.search(folded)
        if mm:
            hits.append((code, mm))
    if not hits:
        return FieldValue(), FieldValue()
    code, mm = hits[0]
    raw = re.sub(r"\s+", " ", text[mm.start() : mm.end()])
    conf = 0.7 if len(hits) == 1 else 0.45
    fv = FieldValue(code, conf, _evidence(text, mm.start(), mm.end(), 30), [h[0] for h in hits[1:]])
    if len(hits) > 1:
        fv.note = "plusieurs motifs possibles"
    return fv, FieldValue(raw[:140], conf, None)


# --------------------------------------------------------------------------- dossier, statut
RE_CASE = re.compile(
    r"(?:n\s?[°o]\.?\s?(?:de\s|du\s)?(?:dossier|pv|proces[- ]verbal|avis|contravention|constat|reference|ref\.?)"
    r"|numero (?:de |du )?(?:dossier|pv|proces[- ]verbal|avis|reference|constat)"
    r"|reference (?:du )?dossier|ref(?:erence)?\s?dossier|\bref\.|\breference|\bdossier\s?(?:n\s?[°o])?|dossiernummer|referentie|\bpv\s?n\s?[°o])"
    r"\s*[:\-]?\s*([a-z0-9][a-z0-9\-/ ]{3,30}?)(?=\s{2,}|\s(?:du|le|en|date|de)\b|[\n,;)]|$)"
)

RE_PAID = re.compile(r"\b(?:payee?|reglee?|acquittee?|soldee?|betaald)\b(?!\s(?:avant|sous|dans|par|en ligne|au))|paiement (?:recu|enregistre|effectue)|(?:avons|a) (?:bien )?recu votre (?:paiement|reglement)")
RE_CONTEST = re.compile(r"contestation|reclamation|\brecours\b|contestee?|requete en exoneration|bezwaar")
RE_DUE = re.compile(r"a payer|a regler|avant le|mise en demeure|relance|dans un delai|veuillez (?:regler|payer|proceder)|te betalen|gelieve")


def normalize_case_number(raw: str) -> str | None:
    s = re.sub(r"[\s\-/.]", "", raw.upper())
    if len(s) < 5 or len(s) > 30 or sum(ch.isdigit() for ch in s) < 4:
        return None
    return s


def find_case_numbers(text: str, folded: str) -> list[tuple[str, int, int]]:
    out = []
    for m in RE_CASE.finditer(folded):
        n = normalize_case_number(text[m.start(1) : m.end(1)])
        if n:
            out.append((n, m.start(), m.end()))
    return out


def extract_case_and_status(text: str, folded: str, paid_amount: float | None) -> tuple[FieldValue, FieldValue]:
    cases = find_case_numbers(text, folded)
    case_fv = FieldValue()
    if cases:
        distinct = []
        for n, _, _ in cases:
            if n not in distinct:
                distinct.append(n)
        n, s, e = cases[0]
        case_fv = FieldValue(n, 0.85 if len(distinct) == 1 else 0.55, _evidence(text, s, e, 5), distinct[1:])
    if RE_PAID.search(folded) or paid_amount:
        status = FieldValue("payee", 0.8 if paid_amount else 0.6)
    elif RE_CONTEST.search(folded):
        status = FieldValue("contestee", 0.6)
    elif RE_DUE.search(folded):
        status = FieldValue("a_payer", 0.6)
    else:
        status = FieldValue("inconnue", 0.5)
    return case_fv, status


# --------------------------------------------------------------------------- assemblage
def parse_fine(text: str, mention_finder=None) -> dict[str, FieldValue]:
    text = clean_text(text)
    folded = fold(text)
    initial, paid, increased_note = extract_amounts(text, folded)
    date_fv, time_fv = extract_date_time(text, folded)
    fields: dict[str, FieldValue] = {
        "amount_initial": initial,
        "amount_paid": paid,
        "fine_date": date_fv,
        "fine_time": time_fv,
    }
    stations = extract_stations(text, folded, mention_finder)
    fields.update(stations)
    fields.update(extract_train(text, folded, [v.value for v in stations.values() if v.value]))
    reason, reason_text = extract_reason(text, folded)
    fields["reason"] = reason
    fields["reason_text"] = reason_text
    case, status = extract_case_and_status(text, folded, paid.value)
    fields["case_number"] = case
    fields["status"] = status
    fields["currency"] = FieldValue("EUR", 0.95 if initial.value is not None else 0.5)
    fields["notes"] = FieldValue(increased_note, 0.9) if increased_note else FieldValue()
    return fields


def split_segments(text: str) -> list[str]:
    """Decoupe un document contenant plusieurs amendes (plusieurs numeros de dossier distincts)."""
    text = clean_text(text)
    folded = fold(text)
    cases = find_case_numbers(text, folded)
    firsts: dict[str, int] = {}
    for n, s, _ in cases:
        firsts.setdefault(n, s)
    if len(firsts) < 2:
        return [text]
    starts = sorted(text.rfind("\n", 0, s) + 1 for s in firsts.values())
    # le bloc qui precede le premier numero (en-tete) est rattache a la premiere amende
    starts[0] = 0
    segments = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
    return [s for s in segments if s.strip()]


def parse_document(text: str, mention_finder=None) -> list[dict[str, dict]]:
    drafts = []
    segments = split_segments(text)
    for seg in segments:
        fields = parse_fine(seg, mention_finder)
        drafts.append({k: v.to_dict() for k, v in fields.items()})
    return drafts


def summarize(draft: dict[str, dict]) -> dict:
    uncertain = [k for k, v in draft.items() if v.get("uncertain")]
    missing = [k for k in ("amount_initial", "fine_date", "origin_name", "dest_name") if draft.get(k, {}).get("value") is None]
    return {"uncertain": uncertain, "missing": missing}


def parse_time_value(v: str | None) -> str | None:
    if not v:
        return None
    m = re.fullmatch(r"\s*([01]?\d|2[0-3])\s*[:hH]\s*([0-5]\d)\s*", v)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def parse_date_value(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return None
