"""Mask personal data in letter text BEFORE it is sent to any LLM.

Each match is replaced by a numbered placeholder like [NAME_1] or [IBAN_1]. The mapping from
placeholder to original value only lives in memory for the current request; it is never
logged or stored. Regex masking is not perfect (that is what Presidio would add in v2), so the
eval checks that the fake names in eval/letters.jsonl never reach a prompt.
"""

import re
from dataclasses import dataclass, field

# Order matters: specific patterns (IBAN, e-mail, IDs) run before broad ones (phone, names).
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
TAX_ID = re.compile(
    r"(?:(?<=Steuer-ID:)|(?<=Steuer-ID)|(?<=Steuer-Identifikationsnummer:)|(?<=IdNr\.:))"
    r"\s*\d{2} ?\d{3} ?\d{3} ?\d{3}\b"
    r"|\b\d{11}\b"
)
CASE_ID = re.compile(
    r"(?<=Aktenzeichen:)\s*[\w./-]+"
    r"|(?<=Az\.:)\s*[\w./-]+"
    r"|(?<=Geschäftszeichen:)\s*[\w./-]+"
    r"|(?<=Kundennummer:)\s*[\w./-]+"
    r"|(?<=Versicherungsnummer:)\s*[\w./-]+"
    r"|(?<=Beitragsnummer:)\s*\d{3} ?\d{3} ?\d{3}"
    r"|\b[A-Z]{2,5}-\d{2,4}-\d{3,6}\b"
)
BIRTH_DATE = re.compile(
    r"(?<=geb\. )\d{1,2}\.\d{1,2}\.\d{2,4}"
    r"|(?<=geboren am )\d{1,2}\.\d{1,2}\.\d{2,4}"
    r"|(?<=Geburtsdatum: )\d{1,2}\.\d{1,2}\.\d{2,4}"
)
# Street line + house number (+ optional postcode/city on the same or next line).
ADDRESS = re.compile(
    r"^(?!Postfach)[A-ZÄÖÜ][^\n,:;]{2,40}? \d{1,4}[a-z]?(?:(?:,\s*|\n)\d{5} [A-ZÄÖÜ][^\n,]*)?$",
    re.MULTILINE,
)
# German phone numbers: +49 / 0049 / 0 + area code + number, at least 7 digits in total.
PHONE = re.compile(r"(?<![\d,.])(?:\+49|0049|0)[ /-]?\(?\d{2,5}\)?[ /-]?\d{3,}(?:[ -]\d{2,})*\b")
# Names after a salutation: "Herrn Arjun Testmann", "Frau Lina Beispiel-Rao".
# Only the named group "v" is replaced, so the salutation itself stays readable.
NAME = re.compile(r"\b(?:Herrn|Herr|Frau) (?P<v>[A-ZÄÖÜ][\wäöüß-]+(?: [A-ZÄÖÜ][\wäöüß-]+){0,2})")

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("IBAN", IBAN),
    ("EMAIL", EMAIL),
    ("TAX_ID", TAX_ID),
    ("CASE_ID", CASE_ID),
    ("BIRTH_DATE", BIRTH_DATE),
    ("ADDRESS", ADDRESS),
    ("PHONE", PHONE),
    ("NAME", NAME),
]


@dataclass
class MaskResult:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder -> original (memory only)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for placeholder in self.mapping:
            kind = placeholder.strip("[]").rsplit("_", 1)[0]
            out[kind] = out.get(kind, 0) + 1
        return out


def mask(text: str) -> MaskResult:
    result = MaskResult(text=text)
    reverse: dict[str, str] = {}  # original -> placeholder, so repeats share one placeholder
    counters: dict[str, int] = {}

    def placeholder_for(kind: str, value: str) -> str:
        if value not in reverse:
            counters[kind] = counters.get(kind, 0) + 1
            reverse[value] = f"[{kind}_{counters[kind]}]"
            result.mapping[reverse[value]] = value
        return reverse[value]

    for kind, pattern in PATTERNS:

        def repl(m: re.Match[str], kind: str = kind) -> str:
            group = "v" if "v" in m.re.groupindex else 0
            raw = m.group(group)
            value = raw.strip()
            if not value:
                return m.group(0)
            if kind == "NAME":  # "Testmann" after "Arjun Testmann": same person, same placeholder
                for known, ph in reverse.items():
                    if ph.startswith("[NAME_") and value in known.split():
                        reverse[value] = ph
                        break
            start, end = m.span(group)
            offset = m.start(0)
            lead = raw[: len(raw) - len(raw.lstrip())]
            return (
                m.group(0)[: start - offset]
                + lead
                + placeholder_for(kind, value)
                + m.group(0)[end - offset :]
            )

        result.text = pattern.sub(repl, result.text)

    # A surname often reappears alone ("Sehr geehrter Herr Testmann"): mask it everywhere too.
    for placeholder, value in list(result.mapping.items()):
        if placeholder.startswith("[NAME_"):
            for part in value.split():
                if len(part) > 2:
                    result.text = re.sub(rf"\b{re.escape(part)}\b", placeholder, result.text)
    return result
