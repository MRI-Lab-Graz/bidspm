"""Path checks for every GUI route that writes a file or creates a folder."""
import logging
import os

log = logging.getLogger(__name__)
PROTECTED_NAMES = ("dataset_description.json", "participants.tsv")


class UnsafePath(ValueError):
    """The path may not be written; str() is the message shown to the user."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def has_nul(value):
    """True when any string inside a JSON value (iterative: nesting depth is attacker-controlled) contains NUL."""
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            if "\x00" in v:
                return True
        elif isinstance(v, dict):
            stack += list(v.keys()) + list(v.values())
        elif isinstance(v, list):
            stack += v
    return False


def _inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def in_bids_tree(path, root):
    """True when `path` is inside the BIDS folder `root` but not inside <root>/derivatives (the standard BIDS layout puts
    derivatives there, and that is where models and outputs belong). Typed and symlink-resolved roots are both tried.
    A root of `/` means no real BIDS folder is configured: nothing is protected by it (dataset files still are)."""
    if not root:
        return False
    for r in {os.path.abspath(root), os.path.realpath(root)}:
        if r == os.sep:
            log.warning("BIDS folder %r is the filesystem root; not used as write protection", root)
            continue
        if _inside(path, r) and not _inside(path, os.path.join(r, "derivatives")):
            return True
    return False


def safe_target(path, base=None, inside=None, protect=(), resolve=None):
    """The real absolute path a GUI write may use, else UnsafePath.

    Expands `~`, rejects NUL and `..` components, and resolves symlinks (os.path.realpath). Refuses dataset_description.json,
    participants.tsv and *_events.tsv anywhere, anything inside a `protect` folder, and anything for which `inside(real)` is true
    (the registered BIDS folders). Both the typed and the resolved path are checked, so a symlink in either direction cannot
    smuggle a write into the BIDS tree. With `base`, `path` is a name under that folder and may not leave it."""
    if not isinstance(path, str) or not path.strip():
        raise UnsafePath("No path provided.")
    if "\x00" in path:
        raise UnsafePath("The path contains a NUL character.")
    typed = os.path.expanduser(path.strip())
    if ".." in typed.replace("\\", "/").split("/"):
        raise UnsafePath("The path must not contain '..'.")
    real_base = None
    if base is not None:
        real_base = os.path.realpath(os.path.expanduser(str(base)))
        typed = os.path.join(real_base, typed)
    if resolve:  # e.g. the GUI's rule for relative paths (anchored at the app root)
        typed = resolve(typed)
    lexical, real = os.path.abspath(typed), os.path.realpath(typed)
    if real_base is not None and not _inside(real, real_base):
        raise UnsafePath(f"{path!r} is outside {base}.", 403)
    name = os.path.basename(real)
    if name.lower() in PROTECTED_NAMES or name.lower().endswith("_events.tsv"):
        raise UnsafePath(f"{name} is a BIDS dataset file; the GUI never writes it.", 403)
    for candidate in {lexical, real}:
        if inside and inside(candidate):
            raise UnsafePath("Writing inside the BIDS folder is not allowed.", 403)
        for root in protect:
            if in_bids_tree(candidate, root):
                raise UnsafePath("Writing inside the BIDS folder is not allowed.", 403)
    return real
