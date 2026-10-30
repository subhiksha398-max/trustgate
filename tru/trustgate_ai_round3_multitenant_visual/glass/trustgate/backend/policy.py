"""Deterministic candidate extraction from approved policy text."""
import math, re
from datetime import datetime

KINDS = {"discount", "warranty", "price", "banned"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}}|(?:{MONTHS})\s+\d{{1,2}},?\s+\d{{4}})"
DATE_RE = re.compile(DATE, re.I)
PERCENT_RE = re.compile(r"(?P<value>\d{1,3}(?:\.\d+)?)\s*(?:%|\bpercent\b|\bper\s+cent\b)", re.I)
WARRANTY_RE = re.compile(r"(?P<value>\d{1,3})\s*[- ]?\s*(?P<unit>years?|months?)\s*(?:limited\s+)?(?:warranty|guarantee)\b", re.I)
PRICE_RE = re.compile(r"(?:₹|\bRs\.?\s*|\$\s*)(?P<value>\d[\d,]*(?:\.\d{1,2})?)", re.I)
BAN_RE = re.compile(r"(?:banned|prohibited|do not use|never use)[^\n:]*:?\s*['\"“](?P<phrase>[^'\"”\n]{2,100})['\"”]", re.I)


def _date(value):
    value = value.strip().replace(",", "")
    for form in ("%Y-%m-%d", "%d %B %Y", "%B %d %Y"):
        try:
            return datetime.strptime(value, form).date().isoformat()
        except ValueError:
            pass
    return ""


def _validity(line):
    dates = DATE_RE.findall(line)
    if len(dates) < 2 or not re.search(r"\b(?:valid|available|offer|promo|promotion)\b", line, re.I):
        return "", ""
    start, end = _date(dates[0]), _date(dates[1])
    return (start, end) if start and end and start <= end else ("", "")


def _subject_after(line, position, fallback):
    match = re.search(r"\b(?:on|for)\s+(?P<subject>[^,.;\n]+)", line[position:], re.I)
    if not match:
        return fallback
    subject = re.split(r"\b(?:valid|until|through|from)\b", match.group("subject"), maxsplit=1, flags=re.I)[0].strip()
    return subject[:120] or fallback


def extract(text, filename):
    """Return conservative proposals; `quote` is always copied from the input text."""
    proposals = []

    def add(kind, subject, value, line, valid_from="", valid_to=""):
        quote = line.strip()
        if not quote or not subject:
            return
        item = {"kind": kind, "subject": subject.strip()[:120], "value": str(value).strip()[:120],
                "valid_from": valid_from, "valid_to": valid_to, "source": filename[:255], "quote": quote[:1000]}
        key = (item["kind"], item["subject"].casefold(), item["value"], item["valid_from"], item["valid_to"], item["quote"])
        if not any((p["kind"], p["subject"].casefold(), p["value"], p["valid_from"], p["valid_to"], p["quote"]) == key for p in proposals):
            proposals.append(item)

    for line in text.splitlines():
        if not line.strip():
            continue
        valid_from, valid_to = _validity(line)
        is_offer = bool(re.search(r"\b(?:offer|promo(?:tion)?|discount|save|off|sale)\b", line, re.I))
        if is_offer:
            for match in PERCENT_RE.finditer(line):
                amount = float(match.group("value"))
                if 0 < amount <= 100:
                    subject = _subject_after(line, match.end(), "all items")
                    add("discount", subject, f"{amount:g}", line, valid_from, valid_to)

        for match in WARRANTY_RE.finditer(line):
            count = int(match.group("value"))
            months = count * 12 if match.group("unit").lower().startswith("year") else count
            if 0 < months <= 1200:
                add("warranty", "all products", str(months), line, valid_from, valid_to)

        if re.search(r"\b(?:price|cost|priced)\b", line, re.I):
            for match in PRICE_RE.finditer(line):
                amount = match.group("value").replace(",", "")
                prefix = line[:match.start()].strip(" :,-\t")
                subject = re.sub(r"\b(?:price|cost|priced|is|at)\b", "", prefix, flags=re.I).strip(" :,-\t")
                add("price", subject[-120:] or "all items", amount, line, valid_from, valid_to)

        for match in BAN_RE.finditer(line):
            add("banned", match.group("phrase").strip(), "", line, valid_from, valid_to)

    return proposals


def validate_ai(items, text, filename):
    """Keep only AI candidates with supported kinds, valid fields, and verbatim evidence."""
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip().lower()
        subject = str(item.get("subject", "")).strip()
        value = str(item.get("value", "")).strip()
        quote = str(item.get("quote", ""))
        if kind not in KINDS or not subject or not quote or quote not in text:
            continue
        valid_from, valid_to = str(item.get("valid_from", "")).strip(), str(item.get("valid_to", "")).strip()
        if any(v and (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) or not _date(v)) for v in (valid_from, valid_to)):
            continue
        if valid_from and valid_to and valid_from > valid_to:
            continue
        if kind == "discount":
            try:
                if not 0 < float(value) <= 100: continue
            except ValueError:
                continue
        elif kind == "warranty":
            try:
                if not 0 < int(value) <= 1200: continue
            except ValueError:
                continue
        elif kind == "price":
            try:
                amount = float(value.replace(",", ""))
                if not math.isfinite(amount) or amount < 0: continue
            except ValueError:
                continue
        out.append({"kind": kind, "subject": subject[:120], "value": value[:120], "valid_from": valid_from,
                    "valid_to": valid_to, "source": filename[:255], "quote": quote[:1000]})
    return out