"""The one TSV reader. BIDS TSVs have no quoting, so a '"' is an ordinary character (csv defaults would merge rows)."""
import csv
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


def count_lines(path):
    """Number of non-header lines, counted on raw bytes (no CSV parsing)."""
    n, last = 0, b"\n"
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            n += chunk.count(b"\n")
            last = chunk[-1:]
    return max(n + (last != b"\n") - 1, 0)


def duplicates(columns):
    """Column names that occur more than once, in first-seen order."""
    seen, dup = set(), []
    for c in columns:
        if c in seen and c not in dup:
            dup.append(c)
        seen.add(c)
    return dup
