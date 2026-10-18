"""Guard: every innerHTML / insertAdjacentHTML / outerHTML sink in the shipped JS and templates must be ONE string
literal of constant markup whose `${...}` interpolations are escaped with escapeHtml() (static/js/dom_safe.js; the
transformer builder has its own escHtml/escAttr). Dataset, model and typed text must never reach the HTML parser as
markup: a file or folder name such as `<img src=x onerror=...>` would run script in the page.

Allow-list: INTERPOLATION_OK holds the prefixes of interpolated expressions that are constants or numbers (never user
text). Computed markup (concatenation, .map().join(), ternaries) is not allowed at a sink: build DOM nodes instead.
A new sink that violates this fails here: escape it, or build DOM nodes with textContent.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"model_wizard.js", "model_wizard_steps.js", "model_wizard.html"}  # covered by the wizard's own tests
SINK = re.compile(r"(?:\.innerHTML\s*\+?=|\.outerHTML\s*=|insertAdjacentHTML\s*\()")
SAFE_CALL = re.compile(r"^(?:escapeHtml|escHtml|escAttr)\(")
INTERPOLATION_OK = (
    "tone", "icon", "option.icon", "section.icon", "classMap[type]", "exists ? ", "item.type === 'dir'",
    "visibleIdx.length", "errorCount", "warnings.length",
    "warningHtml", "formatHintValues(", "formatEventSample(",  # analysis_model_hints.js: return escaped markup
)
# Sinks reviewed by hand (2026-10-18) that build markup from several parts: every user-derived value in them goes
# through escHtml/escAttr, the rest is constant. file -> start of the normalised statement.
REVIEWED = {
    "transformer_builder_columns.js": (".innerHTML = options.emptyHtml ||", ".innerHTML = columnInfos.map("),
    "transformer_builder_model_selection.js": (".innerHTML = (details || []).map(", ".innerHTML = deduped.map("),
    "transformer_builder_pipeline.js": (
        ".innerHTML = columnInfo.generated", '.innerHTML = ` <div class="op-card-header">',
        ".innerHTML = ` <div class=\"val-pills-hint\">", ".innerHTML = values.map(", ".innerHTML = ` <div class=\"val-pills-hint\"><i",
        ".innerHTML = chips.length"),
    "transformer_builder_scan_preview.js": (".innerHTML = '<tr>' + visibleIdx.map(", ".innerHTML = visibleIdx.map(",
                                            ".innerHTML = ` <thead><tr><th>Column</th>"),
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
    for path in (p for p in files if p.name not in SKIP):
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
            if " ".join(stmt.split()).startswith(REVIEWED.get(path.name, ())):
                continue
            if not LITERAL.fullmatch(blank_interpolations(value_of(stmt))):
                bad.append(f"{where} computed markup: {' '.join(stmt.split())[:100]!r}")
                continue
            bad += [f"{where} unescaped ${{{e[:60]}}}" for e in interpolations(stmt)
                    if not (SAFE_CALL.match(e) or e.startswith(INTERPOLATION_OK))]
        self.assertEqual(bad, [], "unsafe HTML sinks:\n" + "\n".join(bad))

    def test_scan_finds_the_known_sinks(self):
        names = {p.name for p, _, _ in scan()}
        self.assertTrue({"analysis_api_actions.js", "projects.html"} <= names)


if __name__ == "__main__":
    unittest.main()
