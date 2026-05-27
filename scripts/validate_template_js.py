#!/usr/bin/env python3
"""Validate embedded JavaScript blocks inside Jinja-flavored HTML templates."""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_BLOCK_PATTERN = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
QUOTED_JINJA_PATTERN = re.compile(r"['\"]\s*\{\{.*?\}\}\s*['\"]", re.DOTALL)
JINJA_EXPRESSION_PATTERN = re.compile(r"\{\{.*?\}\}", re.DOTALL)
JINJA_BLOCK_PATTERN = re.compile(r"\{%.*?%\}", re.DOTALL)
JINJA_COMMENT_PATTERN = re.compile(r"\{#.*?#\}", re.DOTALL)


def strip_jinja(template_text: str) -> str:
    stripped = QUOTED_JINJA_PATTERN.sub('"VAR"', template_text)
    stripped = JINJA_EXPRESSION_PATTERN.sub('0', stripped)
    stripped = JINJA_BLOCK_PATTERN.sub('', stripped)
    stripped = JINJA_COMMENT_PATTERN.sub('', stripped)
    return stripped


def extract_script_blocks(template_text: str) -> list[str]:
    return [
        match.group(1)
        for match in SCRIPT_BLOCK_PATTERN.finditer(template_text)
        if match.group(1).strip()
    ]


def validate_script_blocks(template_path: Path, emit_dir: Path | None = None) -> int:
    template_text = template_path.read_text(encoding='utf-8')
    scripts = extract_script_blocks(template_text)

    if not scripts:
        print(f"No script blocks found in {template_path}.")
        return 0

    if emit_dir is not None:
        emit_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    with tempfile.TemporaryDirectory(prefix='bidspm-template-js-') as tmp_dir:
        temp_root = Path(tmp_dir)
        for index, script in enumerate(scripts):
            stripped = strip_jinja(script)
            check_path = temp_root / f"script_{index}.js"
            check_path.write_text(stripped, encoding='utf-8')

            if emit_dir is not None:
                emitted_path = emit_dir / f"{template_path.stem}.script_{index}.js"
                emitted_path.write_text(stripped, encoding='utf-8')

            try:
                result = subprocess.run(
                    ['node', '--check', str(check_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except FileNotFoundError:
                print('node is required to validate embedded JavaScript.', file=sys.stderr)
                return 2

            if result.returncode == 0:
                print(f"Script block {index} passed.")
                continue

            failures += 1
            print(f"Script block {index} FAILED validation:")
            stderr = (result.stderr or '').strip()
            print(stderr or 'node --check returned a non-zero exit code without stderr output.')

    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('template', help='Path to the HTML/Jinja template to validate.')
    parser.add_argument(
        '--emit-dir',
        help='Optional directory where stripped script blocks should be written for inspection.',
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    template_path = Path(args.template).resolve()
    if not template_path.is_file():
        parser.error(f'template not found: {template_path}')

    emit_dir = Path(args.emit_dir).resolve() if args.emit_dir else None
    return validate_script_blocks(template_path, emit_dir=emit_dir)


if __name__ == '__main__':
    sys.exit(main())