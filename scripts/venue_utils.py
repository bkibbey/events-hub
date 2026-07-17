"""Shared utilities for venue normalization, canonical keys, and slugs.

Used by seed-venues.py and geocode-venues.py.
"""
from __future__ import annotations

import re
import unicodedata

# ----- address normalization -----

_STREET_ABBR = {
    r"\bst\b": "street",
    r"\bstreet\b": "street",
    r"\bave\b": "avenue",
    r"\bavenue\b": "avenue",
    r"\brd\b": "road",
    r"\broad\b": "road",
    r"\bblvd\b": "boulevard",
    r"\bboulevard\b": "boulevard",
    r"\bdr\b": "drive",
    r"\bdrive\b": "drive",
    r"\bln\b": "lane",
    r"\blane\b": "lane",
    r"\bpkwy\b": "parkway",
    r"\bparkway\b": "parkway",
    r"\bhwy\b": "highway",
    r"\bhighway\b": "highway",
    r"\bcir\b": "circle",
    r"\bcircle\b": "circle",
    r"\bct\b": "court",
    r"\bcourt\b": "court",
    r"\bpl\b": "place",
    r"\bplace\b": "place",
    r"\bter\b": "terrace",
    r"\bterrace\b": "terrace",
    r"\btrl\b": "trail",
    r"\btrail\b": "trail",
    r"\bfwy\b": "freeway",
    r"\bfreeway\b": "freeway",
    r"\bplz\b": "plaza",
    r"\bplaza\b": "plaza",
    r"\bsq\b": "square",
    r"\bsquare\b": "square",
    r"\bxing\b": "crossing",
    r"\bcrossing\b": "crossing",
    r"\bwy\b": "way",
    r"\bway\b": "way",
}

# Set of expanded street-type words that terminate the address at their first occurrence
_STREET_TYPE_TERMINATE_RE = re.compile(
    r"\b(?:street|avenue|road|boulevard|drive|lane|parkway|highway|circle|court|"
    r"place|terrace|trail|freeway|plaza|square|crossing|way)\b",
    re.IGNORECASE,
)

_DIR_ABBR = {
    r"\bn\b": "north",
    r"\bs\b": "south",
    r"\be\b": "east",
    r"\bw\b": "west",
    r"\bne\b": "northeast",
    r"\bnw\b": "northwest",
    r"\bse\b": "southeast",
    r"\bsw\b": "southwest",
}

# Match unit designators followed by up to a few short tokens (e.g., 'Ste. B 110')
_UNIT_RE = re.compile(
    r"\b(?:suite|ste|unit|apt|apartment|#|no|number|bldg|building|floor|fl|room|rm)\b\.?\s*(?:[\w\-]+\s*){1,3}",
    re.IGNORECASE,
)

# Trailing ', City, ST [zip]' pattern to strip from address field
_TRAILING_LOCATION_RE = re.compile(
    r",\s*[a-z\.\s]+,\s*(?:nc|north\s+carolina|n\.c\.?)\b\.?(?:\s+\d{5}(?:-\d{4})?)?\s*$",
    re.IGNORECASE,
)

# Placeholder / non-address strings that should be treated as no-address
_PLACEHOLDER_RE = re.compile(
    r"^(?:tbd|tba|t\.b\.d\.?|n\/?a|none|null|unknown|various|various\s+locations|"
    r"see\s+website|see\s+details|multiple\s+locations|downtown|downtown\s+raleigh|"
    r"downtown\s+durham|downtown\s+cary|downtown\s+apex)$",
    re.IGNORECASE,
)


def normalize_address(addr: str | None) -> str:
    """Return a canonicalized street address for grouping.

    Lowercases, drops punctuation, expands common abbreviations, drops unit
    numbers, collapses whitespace. Missing/empty returns ''.
    """
    if not addr:
        return ""
    s = addr.strip()
    # Reject placeholder/non-address strings
    if _PLACEHOLDER_RE.match(s):
        return ""
    # If there's a slash separating two street names, keep only the first
    if "/" in s:
        s = s.split("/")[0].strip()
    # Cut off at first parenthesis (descriptive suffixes like '(above Centro)')
    if "(" in s:
        s = s.split("(")[0].strip()
    # Truncate at first comma — street portion of a US address should be comma-free.
    # This drops city/state/zip and any trailing narrative in one shot.
    if "," in s:
        s = s.split(",")[0].strip()
    # Fallback trailing-location strip (belt and suspenders for un-comma'd cases)
    s = _TRAILING_LOCATION_RE.sub("", s)
    s = s.lower()
    # Strip punctuation except numbers/letters/spaces
    s = re.sub(r"[\.,;:'\"()]", " ", s)
    # Drop units/suites
    s = _UNIT_RE.sub(" ", s)
    # Expand direction abbreviations
    for pat, rep in _DIR_ABBR.items():
        s = re.sub(pat, rep, s)
    # Expand street-type abbreviations
    for pat, rep in _STREET_ABBR.items():
        s = re.sub(pat, rep, s)
    # Collapse whitespace + hyphens
    s = re.sub(r"[\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Truncate after first street-type token to drop trailing narrative like 'above centro'.
    # Only do this if we can identify a street type in the string.
    m = _STREET_TYPE_TERMINATE_RE.search(s)
    if m:
        s = s[: m.end()].strip()
    return s


def normalize_zip(z: str | None) -> str:
    if not z:
        return ""
    m = re.search(r"\d{5}", str(z))
    return m.group(0) if m else ""


def normalize_city(c: str | None) -> str:
    if not c:
        return ""
    return re.sub(r"\s+", " ", c.strip().lower())


def canonical_key(address: str | None, city: str | None, zip_: str | None) -> str:
    """Ground-truth grouping key: normalized_street + city (zip intentionally excluded).

    Some events omit zip and some include it — keying on it would false-split.
    In practice, street+city is unique enough within our metro area.
    Empty if no address.
    """
    a = normalize_address(address)
    if not a:
        return ""
    return f"{a}|{normalize_city(city)}"


# ----- name normalization / slug -----

_NAME_STOPWORDS = re.compile(r"\b(?:the|a|an|at|of|and|&)\b", re.IGNORECASE)
_NAME_TRAIL_QUALIFIERS = re.compile(
    r"\b(?:lot|parking\s*lot|parking|downtown|uptown|main\s*stage|stage|lawn|patio|"
    r"pavilion|amphitheater|amphitheatre)\b",
    re.IGNORECASE,
)


def slugify(name: str) -> str:
    """Return a URL-safe slug for a venue name."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "venue"


def name_key(name: str) -> str:
    """Loose comparable form of a venue name for fuzzy matching.

    Lowercases, drops stopwords + punctuation, collapses whitespace.
    Does NOT strip trailing qualifiers (see qualifier_penalty).
    """
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = _NAME_STOPWORDS.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def qualifier_penalty(name: str) -> int:
    """Score bump for names with trailing/inline qualifiers (higher = worse)."""
    return len(_NAME_TRAIL_QUALIFIERS.findall(name or ""))


def clean_name_for_canonical(name: str) -> str:
    """Prefer this cleaned form when picking canonical display name."""
    s = (name or "").strip()
    # Collapse duplicate spaces
    s = re.sub(r"\s+", " ", s)
    return s
