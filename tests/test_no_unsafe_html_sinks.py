"""Guard: every innerHTML / insertAdjacentHTML / outerHTML sink in the shipped JS and templates must be ONE string
literal of constant markup whose `${...}` interpolations are escaped with escapeHtml() (static/js/dom_safe.js; the
transformer builder has its own escHtml/escAttr). Dataset, model and typed text must never reach the HTML parser as
markup: a file or folder name such as `<img src=x onerror=...>` would run script in the page.

Allow-list: INTERPOLATION_OK holds the exact interpolated expressions that are constants or numbers (never user
text). Computed markup (concatenation, .map().join(), ternaries) is not allowed at a sink: build DOM nodes instead.
A new sink that violates this fails here: escape it, or build DOM nodes with textContent.
"""
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SINK = re.compile(r"(?:\.innerHTML\s*\+?=|\.outerHTML\s*=|insertAdjacentHTML\s*\()")
SAFE_CALL = re.compile(r"^(?:escapeHtml|escHtml|escAttr)\(")
INTERPOLATION_OK = {  # exact expressions, each reviewed as constant markup / class names (never user text)
    "tone", "icon", "option.icon", "section.icon", "iconClass", "visibleIdx.length", "warningHtml",
    "classMap[type] || 'text-muted'", "exists ? 'check' : 'times'", "exists ? 'Path found' : 'Path not found'",
    "item.type === 'dir' ? 'folder text-warning' : (item.name.endsWith('.sif') ? 'box text-success' : 'file-code text-primary')",
    # analysis_model_hints.js: these return escaped markup
    "formatHintValues(normalizeHintArray(dataset.bids_tasks), 'present', 'none detected')",
    "formatHintValues(model.model_tasks, model.field_status.model_tasks, 'not set in model')",
    "formatHintValues(model.contrast_levels, model.field_status.contrast_levels, 'not defined in model')",
    "formatHintValues(model.replace_values, model.field_status.replace_values, 'not used in model')",
    "formatHintValues(normalizeHintArray(events.event_columns), 'present', 'none detected')",
    "formatEventSample(sampleValues.trial_type, sampleStatus.trial_type, 'trial_type column not present')",
    "formatEventSample(sampleValues.condition, sampleStatus.condition, 'condition column not present')",
}
# Sinks reviewed by hand (2026-10-18) that build markup from several parts: every user-derived value in them goes
# through escHtml/escAttr, the rest is constant. file -> sha256[:16] of the WHOLE whitespace-normalised statement, so
# any edit to a reviewed statement (even appending to its tail) fails the guard until it is re-reviewed.
REVIEWED = {
    "transformer_builder_columns.js": {"08e8dcf09d4fea1e", "f12a76fb70a14dfd"},
    "transformer_builder_model_selection.js": {"092d4807bdf9b2ee", "b0d52757e360d1ab"},
    "transformer_builder_pipeline.js": {"f9e9e8f92e145a1e", "ab309e14051cd688", "5f5c796d53fcbced",
                                        "781e24ac328816a1", "bee608aed9dc30d4", "bc347d19a317a760"},
    "transformer_builder_scan_preview.js": {"36b67d7048bfc1f1", "fa7377b080b575f4", "47fcec44719e50d0"},
}
LITERAL = re.compile(r"""\s*(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`)\s*""", re.S)


def statement(text: str, start: int) -> str:
    """Text from the sink to the end of its statement: the first `;` outside quotes and template literals."""
    depth, quote, i = 0, None, start
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif quote == "`" and text.startswith("${", i):
                depth, i = depth + 1, i + 1
            elif c == quote and not depth:
                quote = None
            elif c == "}" and depth:
                depth -= 1
        elif c in "'\"`":
            quote = c
        elif c == ";":
            break
        i += 1
    return text[start:i]


def interpolations(stmt: str):
    for m in re.finditer(r"\$\{", stmt):
        depth, i = 1, m.end()
        while i < len(stmt) and depth:
            depth += {"{": 1, "}": -1}.get(stmt[i], 0)
            i += 1
        yield stmt[m.end():i - 1].strip()


def blank_interpolations(stmt: str) -> str:
    for expr in sorted(set(interpolations(stmt)), key=len, reverse=True):
        stmt = stmt.replace("${" + expr + "}", "")
    return stmt


def scan():
    files = sorted((ROOT / "static" / "js").glob("*.js")) + sorted((ROOT / "templates").glob("*.html"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        for m in SINK.finditer(text):
            yield path, text.count("\n", 0, m.start()) + 1, statement(text, m.start())


def value_of(stmt: str) -> str:
    if stmt.startswith("insertAdjacentHTML"):
        return stmt.split(",", 1)[1].rstrip(") \n")
    return stmt.split("=", 1)[1]


class TestNoUnsafeHtmlSinks(unittest.TestCase):
    def test_sinks_are_constant_or_escaped(self):
        bad = []
        for path, line, stmt in scan():
            where = f"{path.relative_to(ROOT)}:{line}"
            digest = hashlib.sha256(" ".join(stmt.split()).encode()).hexdigest()[:16]
            if digest in REVIEWED.get(path.name, ()):
                continue
            if not LITERAL.fullmatch(blank_interpolations(value_of(stmt))):
                bad.append(f"{where} computed markup: {' '.join(stmt.split())[:100]!r}")
                continue
            bad += [f"{where} unescaped ${{{e[:60]}}}" for e in interpolations(stmt)
                    if not (SAFE_CALL.match(e) or e in INTERPOLATION_OK)]
        self.assertEqual(bad, [], "unsafe HTML sinks:\n" + "\n".join(bad))

    def test_scan_finds_the_known_sinks(self):
        names = {p.name for p, _, _ in scan()}
        self.assertTrue({"analysis_api_actions.js", "projects.html"} <= names)


if __name__ == "__main__":
    unittest.main()
