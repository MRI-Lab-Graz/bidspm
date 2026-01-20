#!/usr/bin/env python3
"""Validation functions for BIDSPM Runner"""

import json
import re
from pathlib import Path
from typing import List

from .config import Config
from .logging_utils import log_debug


def validate_space_availability(config: Config, subjects_to_process: List[str], task: str) -> bool:
    """Validate that the specified SPACE exists in fMRIPrep derivatives for the given subjects and task"""
    log_debug(f"Validating SPACE '{config.SPACE}' for task '{task}'")
    
    found_subjects = []
    missing_subjects = []
    available_spaces = set()
    
    for subject_label in subjects_to_process:
        subject_dir = config.FMRIPREP_DIR / f"sub-{subject_label}"
        if not subject_dir.is_dir():
            missing_subjects.append(subject_label)
            continue
            
        # Look for BOLD files with the specified task
        pattern = f"sub-{subject_label}_*task-{task}_*space-*_desc-preproc_bold.nii.gz"
        bold_files = list(subject_dir.rglob(pattern))
        
        # Extract available spaces for this subject/task
        subject_spaces = set()
        space_found = False
        
        for bold_file in bold_files:
            # Extract space from filename using regex
            space_match = re.search(r'space-([^_]+)', bold_file.name)
            if space_match:
                space_name = space_match.group(1)
                subject_spaces.add(space_name)
                available_spaces.add(space_name)
                
                if space_name == config.SPACE:
                    space_found = True
        
        if space_found:
            found_subjects.append(subject_label)
            log_debug(f"Subject {subject_label}: SPACE '{config.SPACE}' found")
        else:
            missing_subjects.append(subject_label)
            if subject_spaces:
                log_debug(f"Subject {subject_label}: SPACE '{config.SPACE}' NOT found. Available spaces: {sorted(subject_spaces)}")
            else:
                log_debug(f"Subject {subject_label}: No BOLD files found for task '{task}'")
    
    # Report results
    if missing_subjects:
        print("❌ SPACE validation failed!")
        print(f"   Specified SPACE: '{config.SPACE}'")
        print(f"   Task: '{task}'")
        print(f"   Subjects missing SPACE '{config.SPACE}': {missing_subjects}")
        if available_spaces:
            print(f"   Available spaces found: {sorted(available_spaces)}")
            print("   💡 Suggestion: Update SPACE in config/config.json to one of the available spaces")
        else:
            print(f"   ⚠️  No BOLD files found for task '{task}' in any subject")
        return False
    
    print(f"✅ SPACE validation passed: '{config.SPACE}' found for all {len(found_subjects)} subjects")
    return True


def ensure_derivatives_dataset_description(derivatives_dir: Path):
    """Create a minimal dataset_description.json in derivatives directory to suppress BIDSPM warnings."""
    dataset_desc_file = derivatives_dir / "dataset_description.json"
    
    if not dataset_desc_file.exists():
        minimal_description = {
            "Name": "Derivatives",
            "BIDSVersion": "1.8.0",
            "DatasetType": "derivative",
            "GeneratedBy": [
                {
                    "Name": "bidspm-runner",
                    "Version": "1.0.0",
                    "Description": "Minimal dataset description to satisfy BIDS validation"
                }
            ]
        }
        
        try:
            with open(dataset_desc_file, 'w') as f:
                json.dump(minimal_description, f, indent=2)
            log_debug(f"Created minimal dataset_description.json in {derivatives_dir}")
        except Exception as e:
            log_debug(f"Could not create dataset_description.json: {e}")
