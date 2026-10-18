"""The one TSV reader. BIDS TSVs have no quoting, so a '"' is an ordinary character (csv defaults would merge rows)."""
import csv
import re
from contextlib import contextmanager


def dict_reader(fh):
    """DictReader over an open text file: tab-delimited, quotes literal."""
    return csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)


@contextmanager
def open_tsv(path):
    """Yield a dict_reader over path (utf-8-sig: a BOM never leaks into the first column name)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        yield dict_reader(fh)


def read_tsv(path):
    """(columns, rows). Duplicate column names collapse in the row dicts; use duplicates(columns) to report them."""
    with open_tsv(path) as reader:
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def read_head(path):
    """(column names, first data row or None): two lines only, confounds files are huge."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        return next(reader, []), next(reader, None)


def read_header(path):
    return read_head(path)[0]


_BLANK_LINE = re.compile(rb"\n[ \t\r]*(?=\n)")  # an empty or whitespace-only line terminated by a newline
QUOTE_WARNING = "values are wrapped in quotes; BIDS TSV files must not quote fields"


def count_lines(path):
    """Number of non-header, non-blank lines, counted on raw bytes (no CSV parsing). LF, CRLF and CR-only endings."""
    with open(path, "rb") as fh:
        data = fh.read()
    if b"\n" not in data:
        data = data.replace(b"\r", b"\n")
    n = data.count(b"\n") - sum(1 for _ in _BLANK_LINE.finditer(data))
    n += bool(data[data.rfind(b"\n") + 1:].strip())  # last line without a final newline
    return max(n - 1, 0)


def quoted(values):
    """True when a field is wrapped in double quotes. This module reads quotes literally (as bids-matlab does), so the
    caller shows QUOTE_WARNING: a stray quote inside a value is data, a wrapped field is a mistake."""
    return any(isinstance(v, str) and len(v) >= 2 and v[0] == v[-1] == '"' for v in values)


def has_quotes(path):
    header, first = read_head(path)
    return quoted(header) or quoted(first or [])


def duplicates(columns):
    """Column names that occur more than once, in first-seen order."""
    seen, dup = set(), []
    for c in columns:
        if c in seen and c not in dup:
            dup.append(c)
        seen.add(c)
    return dup
