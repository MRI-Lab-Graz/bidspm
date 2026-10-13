# Working agreements

- **TDD, always** (`superpowers:test-driven-development`): write a failing test first, then the code. Applies to every feature and bugfix. Throwaway spikes (e.g. probing whether a tool runs) are exempt, but anything kept gets a test.
- **Ponytail before merging to main**: run `/ponytail:ponytail-review` on the branch diff (and `/ponytail:ponytail-audit` for larger changes) and resolve or consciously defer its findings before merging.
- The GUI only triggers `bidspm.py` CLI commands; pipeline logic belongs in the CLI/`lib/`, not in `webapp/`.
- Tests: `python -m pytest -q tests`.
