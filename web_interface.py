#!/usr/bin/env python3
"""Compatibility launcher for the renamed BIDSPM GUI entrypoint.

Preferred entrypoint: `python bidspm_gui.py`
Legacy entrypoint kept for backwards compatibility: `python web_interface.py`
"""

from bidspm_gui import app  # re-export for tools expecting FLASK_APP=web_interface.py


if __name__ == '__main__':
    import runpy

    runpy.run_module('bidspm_gui', run_name='__main__')
