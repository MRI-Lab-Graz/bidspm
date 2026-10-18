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


def read_header(path):
    """Column names only: confounds files are huge."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return next(csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE), [])


def duplicates(columns):
    """Column names that occur more than once, in first-seen order."""
    seen, dup = set(), []
    for c in columns:
        if c in seen and c not in dup:
            dup.append(c)
        seen.add(c)
    return dup
