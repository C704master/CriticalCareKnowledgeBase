"""Evidence markers used in compressed-case generation, review and reporting."""
import re
from bisect import bisect_left
from itertools import accumulate

RANGE = r"[-–—至]"
SEPARATOR = r"[,，、]"
NUMBER = r"\d+"
FIRST = rf"E\s*{NUMBER}"
NEXT = rf"E?\s*{NUMBER}"


def bracketed(body):
    return rf"(?:\[\s*{body}\s*\]|【\s*{body}\s*】|［\s*{body}\s*］)"


SINGLE = bracketed(FIRST)
GROUP = bracketed(rf"{FIRST}(?:\s*(?:{SEPARATOR}|{RANGE})\s*{NEXT})*")
MARKER = re.compile(rf"{SINGLE}\s*{RANGE}\s*{SINGLE}|{GROUP}")
TOKEN = re.compile(rf"{NUMBER}|{RANGE}|{SEPARATOR}")


def marker_ids(marker):
    """Expand ascending ranges within the historical 1..100 review limit."""
    ids = []
    previous = None
    separator = ""
    for token in TOKEN.findall(marker):
        if not token.isdecimal():
            separator = token
            continue
        current = int(token)
        if (previous is not None and re.fullmatch(RANGE, separator)
                and 1 <= previous < current <= 100):
            ids.extend(range(previous + 1, current))
        ids.append(current)
        previous = current
    return ids


def refs(text):
    """Return unique IDs in first-mention order, including out-of-evidence IDs."""
    return list(dict.fromkeys(n for m in MARKER.finditer(text) for n in marker_ids(m[0])))


def refs_by_line(text):
    """Attach a marker to its closing line, including markers split across lines."""
    ends = list(accumulate(map(len, text.splitlines(keepends=True))))
    by_line = {}
    for m in MARKER.finditer(text):
        line = bisect_left(ends, m.end())
        by_line.setdefault(line, []).extend(marker_ids(m[0]))
    return {line: list(dict.fromkeys(ids)) for line, ids in by_line.items()}


def without_refs(text):
    """Hide exactly the markers the counters recognize, preserving line breaks."""
    return MARKER.sub(lambda m: re.sub(r"[^\r\n]", "", m[0]), text)

