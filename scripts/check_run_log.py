#!/usr/bin/env python3
"""Fail (exit 1) if a bidspm run log has any error/warning not on the allow-list.

Allowed lines are data- or Octave-dependent notices, not defects: contrasts without
suprathreshold voxels, missing slice timing, Octave lacking goodness-of-fit/IC.
"""
import re
import sys

SUSPECT = re.compile(r"error|warning|traceback|exception|fail|not found|denied|cannot|unable|could not", re.I)
ALLOWED = [re.compile(p) for p in (
    r"^warning: ?$",  # bare header printed before a bidspm WARNING block
    r"bidspm - WARNING\s+(labelActivations|setBatchSubjectLevelGLMSpec|setBatchGoodnessOfFit"
    r"|setBatchInformationCriteria|checkMaskOrUnderlay|overwriteDir|getInclusiveMask)\b",  # overwriteDir: re-run over an existing folder; getInclusiveMask: several runs, run-1 mask used
    r"More than 1 mask image found",
    r"No voxels survive (height|extent) threshold",
    r"Could not find specified file for mask/montage",  # checkMaskOrUnderlay falls back to the SPM mask
    r"OpenGL Startup options have been removed",  # MATLAB Runtime R2026a start-up notice (SPM standalone)
    r"Subjects failed: 0\b",
)]


def find_problems(text: str) -> list[str]:
    return [ln for ln in text.splitlines()
            if SUSPECT.search(ln) and not any(p.search(ln) for p in ALLOWED)]


if __name__ == "__main__":
    problems = find_problems(open(sys.argv[1], encoding="utf-8", errors="replace").read())
    for p in problems:
        print(p)
    print(f"{len(problems)} problem line(s)")
    sys.exit(1 if problems else 0)
