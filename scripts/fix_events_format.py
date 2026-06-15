#!/usr/bin/env python3
"""
Fix BIDS events file formatting for MRAUT task:
- Simplify trial_type to categorical values: fixation, item, button_press, verbal_response, rating
- Extract item names, ratings, and button types into separate columns
- Fix Keyboard events: duration=0, onset=original_onset+response_time
- Batch process folder and rename to match BIDS bold files
"""

import pandas as pd
import sys
import re
import shutil
import unicodedata
from pathlib import Path
from glob import glob


PASSTHROUGH_TASKS = {'MRECO', 'MREOC'}


def normalize_label(value):
    """Normalize labels for resilient subject and item matching."""
    text = ''.join(
        char for char in unicodedata.normalize('NFKD', str(value or ''))
        if not unicodedata.combining(char)
    )
    text = text.casefold().strip()
    return re.sub(r'[^a-z0-9]+', '', text)


def sanitize_column_name(value):
    """Convert external column labels into BIDS-friendly snake_case names."""
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_').lower()
    return text or 'metadata'


def clean_metadata_value(value):
    """Convert spreadsheet values into stable TSV-friendly strings."""
    if pd.isna(value):
        return 'n/a'
    if isinstance(value, float):
        return f"{value:g}"
    text = str(value).strip()
    return text if text else 'n/a'


class ItemMetadataMatcher:
    """Match item rows to spreadsheet metadata, preferring exact names then order."""

    def __init__(self, metadata_columns, records):
        self.metadata_columns = metadata_columns
        self.records = records
        self.used = [False] * len(records)
        self.next_unused = 0
        self.by_name = {}
        for index, record in enumerate(records):
            self.by_name.setdefault(record['_normalized_item'], []).append(index)

    def _claim_index(self, index):
        self.used[index] = True
        while self.next_unused < len(self.used) and self.used[self.next_unused]:
            self.next_unused += 1
        return {
            column: self.records[index].get(column, 'n/a')
            for column in self.metadata_columns
        }

    def claim(self, item_name):
        normalized_item = normalize_label(item_name)
        for index in self.by_name.get(normalized_item, []):
            if not self.used[index]:
                return self._claim_index(index)

        if self.next_unused < len(self.records):
            return self._claim_index(self.next_unused)

        return None


def find_matching_excel(events_file, excel_dir=None):
    """Find a subject-matched Excel workbook for the source events file."""
    events_path = Path(events_file)
    subject = parse_bids_filename(events_path.name).get('sub')
    if not subject:
        return None

    search_dir = Path(excel_dir) if excel_dir else Path(__file__).resolve().parent
    if not search_dir.exists():
        return None

    # Also try the subject code with a leading digit-only prefix stripped (e.g. '141Z682S' → 'Z682S')
    # so that rating files named like 'Z682S.xlsx' match subject 'sub-141Z682S'.
    suffix = re.sub(r'^\d+', '', subject)
    targets = {normalize_label(subject), normalize_label(f"sub-{subject}"), normalize_label(suffix)}
    candidates = sorted(search_dir.glob('*.xlsx')) + sorted(search_dir.glob('*.XLSX'))
    for candidate in candidates:
        normalized_stem = normalize_label(candidate.stem)
        if normalized_stem in targets:
            return candidate
        if normalized_stem.startswith('sub') and normalized_stem[3:] in targets:
            return candidate

    return None


def load_item_metadata_matcher(excel_path):
    """Load item metadata from the first sheet of an Excel workbook."""
    try:
        metadata_df = pd.read_excel(excel_path, engine='openpyxl')
    except ImportError as exc:
        raise RuntimeError(
            "Reading item metadata from Excel requires openpyxl. Install it with 'pip install openpyxl'."
        ) from exc

    metadata_df = metadata_df.dropna(how='all')
    if metadata_df.empty:
        return None

    item_column = metadata_df.columns[0]
    metadata_columns = [sanitize_column_name(column) for column in metadata_df.columns[1:]]
    records = []

    for _, row in metadata_df.iterrows():
        item_name = clean_metadata_value(row[item_column])
        if item_name == 'n/a':
            continue

        record = {'_normalized_item': normalize_label(item_name)}
        for source_column, output_column in zip(metadata_df.columns[1:], metadata_columns):
            record[output_column] = clean_metadata_value(row[source_column])
        records.append(record)

    if not records:
        return None

    return ItemMetadataMatcher(metadata_columns, records)


def load_item_metadata_for_events(events_file, excel_dir=None):
    """Load workbook metadata for a source events file when a matching workbook exists."""
    excel_path = find_matching_excel(events_file, excel_dir=excel_dir)
    if not excel_path:
        return None, None
    return load_item_metadata_matcher(excel_path), excel_path


def fix_events_dataframe(df, item_metadata=None):
    """Fix the events dataframe formatting."""

    def col(row, name, default='n/a'):
        """Safely get a column value, returning default if column is absent."""
        if name not in df.columns:
            return default
        val = row[name]
        return default if (val != val or val is None) else val  # NaN check

    def numeric_response_time(value):
        """Return a float response time when valid, otherwise None."""
        if value == 'n/a' or value is None or not pd.notna(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    metadata_columns = item_metadata.metadata_columns if item_metadata else []

    def make_event(onset, duration, response_time='n/a'):
        event = {
            'onset': onset,
            'duration': duration,
            'trial_type': 'n/a',
            'item': 'n/a',
            'rating': 'n/a',
            'rating_type': 'n/a',
            'button_type': 'n/a',
            'response_time': response_time if response_time != 'n/a' and pd.notna(response_time) else 'n/a',
            'aut_response': 'n/a',
            'valid_response': 'n/a',
        }
        for column in metadata_columns:
            event[column] = 'n/a'
        return event

    # Create output dataframe
    new_rows = []

    i = 0
    while i < len(df):
        row = df.iloc[i]

        event_type = str(col(row, 'event_type', ''))
        trial_type = str(col(row, 'trial_type', ''))
        onset = float(row['onset'])
        duration = col(row, 'duration', 0)
        response_time = col(row, 'response_time', 'n/a')
        
        # Check if next row is a paired Keyboard event (same onset)
        has_keyboard_pair = False
        keyboard_row = None
        if i + 1 < len(df):
            next_row = df.iloc[i + 1]
            if str(next_row['event_type']) == 'Keyboard' and float(next_row['onset']) == onset:
                has_keyboard_pair = True
                keyboard_row = next_row
        
        # Handle standalone Keyboard at end (like thx_key)
        if event_type == 'Keyboard' and not has_keyboard_pair:
            # Check if previous row had same onset (already processed)
            if i > 0 and float(df.iloc[i-1]['onset']) == onset:
                i += 1
                continue
            # Standalone keyboard event
            kb_event = make_event(onset, 0)
            kb_event['trial_type'] = 'button_press'
            kb_event['button_type'] = trial_type.replace('_key', '')
            new_rows.append(kb_event)
            i += 1
            continue
        
        # Skip Keyboard rows that are part of a pair (they'll be processed with their pair)
        if event_type == 'Keyboard':
            i += 1
            continue
        
        # Initialize new event
        new_event = make_event(onset, duration, response_time=response_time)
        
        # === FIXATION ===
        if event_type == 'TextStim' and trial_type == 'fixation':
            new_event['trial_type'] = 'fixation'
        
        # === ITEM presentation (AUTitem Krawatte) ===
        elif event_type.startswith('AUTitem '):
            item_name = event_type.replace('AUTitem ', '')
            new_event['trial_type'] = 'item'
            new_event['item'] = item_name
            metadata = item_metadata.claim(item_name) if item_metadata else None
            if metadata:
                for column, value in metadata.items():
                    new_event[column] = value
        
        # === VERBAL RESPONSE (response2 Krawatte) ===
        elif event_type == 'AUTresponse':
            response_match = re.match(r'response\d*\s+(.+)', trial_type)
            if response_match:
                new_event['item'] = response_match.group(1)
            new_event['trial_type'] = 'verbal_response'
            new_event['aut_response'] = col(row, 'aut_response')
            new_event['valid_response'] = col(row, 'valid_response')
        
        # === SELF RATING (likertRating 2) ===
        elif event_type == 'AUTselfrating':
            rating_match = re.match(r'likertRating\s+(\d+)', trial_type)
            if rating_match:
                new_event['rating'] = rating_match.group(1)
            new_event['trial_type'] = 'rating'
            new_event['rating_type'] = 'self'
        
        # === INSIGHT POSSIBLE (insight_possible 1) ===
        elif event_type == 'possible_insight':
            insight_match = re.match(r'insight_possible\s+(\d+)', trial_type)
            if insight_match:
                new_event['rating'] = insight_match.group(1)
            new_event['trial_type'] = 'rating'
            new_event['rating_type'] = 'insight_possible'
        
        # === INSIGHT INTENSITY (insight_intensity 2) ===
        elif event_type == 'insight_intensity':
            intensity_match = re.match(r'insight_intensity\s+(\d+)', trial_type)
            if intensity_match:
                new_event['rating'] = intensity_match.group(1)
            new_event['trial_type'] = 'rating'
            new_event['rating_type'] = 'insight_intensity'
        
        else:
            # Fallback: keep original
            new_event['trial_type'] = trial_type
        
        new_rows.append(new_event)
        
        # Process paired Keyboard event as button_press with adjusted onset
        if has_keyboard_pair:
            kb_response_time = col(keyboard_row, 'response_time', 'n/a')
            kb_trial_type = str(col(keyboard_row, 'trial_type', ''))
            rt_value = numeric_response_time(kb_response_time)

            # Only emit paired button events when we have a valid response time.
            # Timeout rows often carry a Keyboard placeholder with missing response time.
            if rt_value is not None:
                new_onset = onset + rt_value

                # Determine button type from trial_type (remove _key suffix)
                button_type = kb_trial_type.replace('_key', '')
                # Map specific button types
                button_type_map = {
                    'AUTidea': 'idea',
                    'rating': 'rating',
                    'insight': 'insight',
                    'insight_intensity': 'insight_intensity'
                }
                button_type = button_type_map.get(button_type, button_type)

                kb_event = make_event(round(new_onset, 4), 0)
                kb_event['trial_type'] = 'button_press'
                kb_event['button_type'] = button_type
                new_rows.append(kb_event)
            
            # Skip the keyboard row
            i += 1
        
        i += 1
    
    # Propagate valid_response and aut_response from verbal_response rows back to their item row.
    # Used when the source TSV itself carries these columns on verbal_response events.
    for vr_idx, vr_row in enumerate(new_rows):
        if vr_row['trial_type'] != 'verbal_response' or vr_row['item'] == 'n/a':
            continue
        if vr_row['valid_response'] == 'n/a' and vr_row['aut_response'] == 'n/a':
            continue
        for item_idx in range(vr_idx - 1, -1, -1):
            candidate = new_rows[item_idx]
            if candidate['trial_type'] == 'item' and candidate['item'] == vr_row['item']:
                candidate['valid_response'] = vr_row['valid_response']
                candidate['aut_response'] = vr_row['aut_response']
                break

    # Forward-propagate item-level metadata (from Excel) to verbal_response and rating rows
    # within the same trial block. fixation and button_press are left as n/a.
    if metadata_columns:
        propagate_to = {'verbal_response', 'rating'}
        current_meta = {}
        for row in new_rows:
            tt = row['trial_type']
            if tt == 'item':
                current_meta = {col: row[col] for col in metadata_columns}
            elif tt in propagate_to and current_meta:
                for col, val in current_meta.items():
                    row[col] = val

    # Create output dataframe with column order.
    # aut_response / valid_response may also come from metadata_columns (Excel); skip duplicates.
    columns = ['onset', 'duration', 'trial_type', 'item', 'rating', 'rating_type', 'button_type',
               'response_time', 'aut_response', 'valid_response']
    for col_name in metadata_columns:
        if col_name not in columns:
            columns.append(col_name)
    result_df = pd.DataFrame(new_rows, columns=columns)
    
    # Sort by onset
    result_df = result_df.sort_values('onset').reset_index(drop=True)
    
    # Clean up n/a values
    result_df = result_df.fillna('n/a')
    
    return result_df


def fix_single_file(input_path, output_path=None, excel_dir=None):
    """Fix a single events file."""
    df = pd.read_csv(input_path, sep='\t')
    item_metadata, _ = load_item_metadata_for_events(input_path, excel_dir=excel_dir)
    result_df = fix_events_dataframe(df, item_metadata=item_metadata)
    
    if output_path is None:
        p = Path(input_path)
        output_path = p.parent / f"{p.stem}_fixed{p.suffix}"
    
    result_df.to_csv(output_path, sep='\t', index=False)
    return result_df


def parse_bids_filename(filename):
    """Extract BIDS entities from filename."""
    entities = {}
    # Match patterns like sub-XXX, ses-XXX, task-XXX, etc.
    pattern = r'(sub|ses|task|run|acq|rec|dir|space)-([^_]+)'
    matches = re.findall(pattern, filename)
    for key, value in matches:
        entities[key] = value
    return entities


def find_matching_bold(events_file, bids_func_folder, preferred_task=None):
    """Find the matching bold file for an events file based on sub/ses/task."""
    events_entities = parse_bids_filename(events_file.name)
    
    sub = events_entities.get('sub')
    ses = events_entities.get('ses')
    source_task = preferred_task if preferred_task else events_entities.get('task')
    
    if not sub:
        return None
    
    # Build search pattern. Prefer exact task matching to avoid cross-task collisions.
    if ses:
        if source_task:
            pattern = f"sub-{sub}_ses-{ses}_task-{source_task}_bold.nii*"
        else:
            pattern = f"sub-{sub}_ses-{ses}_task-*_bold.nii*"
    else:
        if source_task:
            pattern = f"sub-{sub}_task-{source_task}_bold.nii*"
        else:
            pattern = f"sub-{sub}_task-*_bold.nii*"
    
    bold_files = list(Path(bids_func_folder).glob(pattern))
    
    if bold_files:
        return bold_files[0]
    return None


def generate_bids_events_name(bold_file):
    """Generate the events filename from a bold filename."""
    # sub-141Z599A_ses-1_task-crom_bold.nii.gz -> sub-141Z599A_ses-1_task-crom_events.tsv
    name = bold_file.name
    # Remove .nii.gz or .nii
    name = re.sub(r'\.nii(\.gz)?$', '', name)
    # Replace _bold with _events
    name = re.sub(r'_bold$', '_events.tsv', name)
    return name


def backup_existing_files(target_dir, file_pattern):
    """Backup existing files matching pattern to a timestamped subdirectory."""
    from datetime import datetime
    target_path = Path(target_dir)
    existing = list(target_path.glob(file_pattern))
    if not existing:
        return
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = target_path / f"backup_events_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Creating backup directory: {backup_dir}")
    for f in existing:
        print(f"    Backing up (copy): {f.name}")
        shutil.copy2(str(f), backup_dir / f.name)  # copy, never move – originals stay in BIDS


def process_folder(source_folder, dest_folder, force=False, dry_run=False, excel_dir=None):
    """
    Process all events files in source folder and copy to dest folder with BIDS naming.
    
    Args:
        source_folder: Folder containing source events TSV files
        dest_folder: BIDS func folder containing bold files (used for naming)
        force:    If True, overwrite existing files. Otherwise skip them.
        dry_run: If True, only show what would be done
    """
    source_path = Path(source_folder)
    dest_path = Path(dest_folder)
    
    if not source_path.exists():
        print(f"Error: Source folder does not exist: {source_folder}")
        return
    
    if not dest_path.exists():
        print(f"Error: Destination folder does not exist: {dest_folder}")
        return
    
    # Find all events TSV files in source
    events_files = list(source_path.glob('*events*.tsv')) + list(source_path.glob('*_task-*.tsv'))
    events_files = list(set(events_files))  # Remove duplicates
    
    if not events_files:
        print(f"No events files found in {source_folder}")
        return
    
    print(f"Found {len(events_files)} events file(s) in source folder")
    print(f"Destination: {dest_folder}")
    print("-" * 60)
    
    processed = 0
    for events_file in sorted(events_files):
        print(f"\nProcessing: {events_file.name}")
        
        # Find matching bold file
        bold_file = find_matching_bold(events_file, dest_folder)
        
        if bold_file:
            new_name = generate_bids_events_name(bold_file)
            output_path = dest_path / new_name
            print(f"  Matched bold: {bold_file.name}")
            print(f"  Output name:  {new_name}")
        else:
            # No matching bold found - keep original name with _fixed suffix
            new_name = events_file.stem.replace('_events', '') + '_events.tsv'
            output_path = dest_path / new_name
            print(f"  No matching bold found, using: {new_name}")
        
        if dry_run:
            exists = output_path.exists()
            action = "[DRY RUN] Would skip (exists, no --force)" if exists and not force else "[DRY RUN] Would create"
            print(f"  {action}: {output_path}")
        else:
            if output_path.exists() and not force:
                print(f"  Skipped (already exists, use --force to overwrite): {output_path}")
                continue
            # Read, fix, and save
            try:
                df = pd.read_csv(events_file, sep='\t')
                item_metadata, excel_path = load_item_metadata_for_events(events_file, excel_dir=excel_dir)
                if excel_path:
                    print(f"  Matched metadata workbook: {excel_path.name}")
                result_df = fix_events_dataframe(df, item_metadata=item_metadata)
                result_df.to_csv(output_path, sep='\t', index=False)
                print(f"  Created: {output_path}")
                processed += 1
            except Exception as e:
                print(f"  ERROR: {e}")

    print("-" * 60)
    print(f"Processed {processed} file(s)")


def process_folder_to_bids(source_folder, bids_root, task=None, source_task=None,
                          ses_override=None, run=None, force=False,
                          excel_dir=None,
                          backup=False, dry_run=False):
    """
    Process all events files in source folder and copy to correct BIDS paths.

    Parses sub-XXX and ses-XXX from each filename and writes reformatted files to
    <bids_root>/sub-XXX/ses-XXX/func/  (mirroring events2bids.sh behaviour).

    Args:
        source_folder: Folder containing source events TSV files
        bids_root:     Root of the BIDS dataset
        task:          Task label for output filename (e.g. 'crom').
                       When given, bold-file matching is skipped.
        source_task:   Source task label filter from input filenames
                       (e.g. 'MRAUT'). Use this when source folder contains
                       multiple tasks and only one should be converted.
        ses_override:  Session label override (e.g. '1'). Replaces value
                       parsed from the source filename.
        run:           Run index to include in output filename (e.g. '1').
                       Inserted between task and 'events' if provided.
        force:         If True, overwrite existing files. Otherwise skip them.
        backup:        If True, back up existing events files before writing
        dry_run:       If True, only show what would be done
    """
    source_path = Path(source_folder)
    bids_path = Path(bids_root)

    if not source_path.exists():
        print(f"Error: Source folder does not exist: {source_folder}")
        return

    if not bids_path.exists():
        print(f"Error: BIDS root does not exist: {bids_root}")
        return

    events_files = sorted(source_path.glob('*_events.tsv'))
    if not events_files:
        print(f"No *_events.tsv files found in {source_folder}")
        return

    # Build a source-task inventory so multi-task folders can be handled safely.
    file_info = []
    source_tasks_found = set()
    for events_file in events_files:
        entities = parse_bids_filename(events_file.name)
        src_task = entities.get('task')
        if src_task:
            source_tasks_found.add(src_task)
        file_info.append((events_file, entities, src_task))

    selected_info = file_info
    if source_task:
        selected_info = [info for info in file_info if (info[2] or '').lower() == source_task.lower()]
        if not selected_info:
            detected = ', '.join(sorted(source_tasks_found)) if source_tasks_found else 'none'
            print(f"Error: No files matched --source-task {source_task}.")
            print(f"Detected source tasks: {detected}")
            return
    elif task and len(source_tasks_found) > 1:
        detected = ', '.join(sorted(source_tasks_found))
        print("Error: Multiple source tasks detected while using a single output --task label.")
        print(f"Detected source tasks: {detected}")
        print("Use --source-task <TASK> to convert one task at a time (example: --source-task MRAUT).")
        return

    print(f"Found {len(events_files)} events file(s)")
    if source_tasks_found:
        print(f"Detected source tasks: {', '.join(sorted(source_tasks_found))}")
    if source_task:
        print(f"Selected source task: {source_task} ({len(selected_info)} file(s))")
    print(f"BIDS root: {bids_root}")
    print("-" * 60)

    processed = 0
    written_outputs = {}
    missing_func_dirs = []
    for events_file, entities, src_task in selected_info:
        print(f"\nProcessing: {events_file.name}")

        # Sanity check – skip tiny files
        line_count = sum(1 for _ in events_file.open())
        if line_count <= 5:
            print(f"  Warning: File seems too small ({line_count} lines), skipping.")
            continue

        sub = entities.get('sub')
        ses = ses_override if ses_override else entities.get('ses')

        if not sub:
            print(f"  Warning: Could not parse 'sub' from filename, skipping.")
            continue

        # Construct BIDS func path
        if ses:
            func_dir = bids_path / f"sub-{sub}" / f"ses-{ses}" / "func"
        else:
            func_dir = bids_path / f"sub-{sub}" / "func"

        if not func_dir.exists():
            print(f"  Skipping: {func_dir} does not exist (no func data).")
            missing_func_dirs.append(str(func_dir))
            continue

        # Determine output filename
        if task:
            # Build name directly from parsed entities + explicit labels
            parts = [f"sub-{sub}"]
            if ses:
                parts.append(f"ses-{ses}")
            parts.append(f"task-{task}")
            if run:
                parts.append(f"run-{run}")
            new_name = "_".join(parts) + "_events.tsv"
            print(f"  Output name: {new_name}")
        else:
            # Try to match a bold file for proper BIDS naming
            bold_file = find_matching_bold(events_file, func_dir, preferred_task=src_task) if func_dir.exists() else None
            if bold_file:
                new_name = generate_bids_events_name(bold_file)
                print(f"  Matched bold: {bold_file.name} -> {new_name}")
            else:
                new_name = events_file.name
                print(f"  No matching bold found, keeping name: {new_name}")

        output_path = func_dir / new_name
        print(f"  Output: {output_path}")

        # Guard against accidental overwrite when multiple source files map to one output.
        if output_path in written_outputs:
            prev = written_outputs[output_path]
            print(f"  Skipping: output already assigned to {prev} in this run.")
            continue

        try:
            df = pd.read_csv(events_file, sep='\t')
            if (src_task or '').upper() in PASSTHROUGH_TASKS:
                print(f"  Pass-through: keeping {src_task} content unchanged.")
                result_df = df
            else:
                item_metadata, excel_path = load_item_metadata_for_events(events_file, excel_dir=excel_dir)
                if excel_path:
                    print(f"  Matched metadata workbook: {excel_path.name}")
                result_df = fix_events_dataframe(df, item_metadata=item_metadata)
        except Exception as e:
            print(f"  ERROR reading/processing source: {e}")
            continue

        if dry_run:
            exists = output_path.exists()
            action = "[DRY RUN] Would skip (already up to date)" if exists else "[DRY RUN] Would write"
            print(f"  {action}: {output_path}")
            continue

        # If the file exists, only skip if the content is already identical
        if output_path.exists() and not force:
            try:
                existing_df = pd.read_csv(output_path, sep='\t')
                if existing_df.equals(result_df):
                    print(f"  Already up to date: {output_path}")
                    continue
            except Exception:
                pass  # Can't read existing file – fall through and overwrite

        if backup and output_path.exists():
            backup_existing_files(func_dir, '*_events.tsv')

        try:
            result_df.to_csv(output_path, sep='\t', index=False)
            print(f"  Created: {output_path}")
            processed += 1
            written_outputs[output_path] = events_file.name
        except Exception as e:
            print(f"  ERROR writing output: {e}")

    print("-" * 60)
    print(f"Processed {processed} file(s)")
    if backup:
        print("Note: Existing files were backed up to timestamped backup directories.")

    if missing_func_dirs:
        print(f"\nMissing func folders ({len(missing_func_dirs)}) – no events written:")
        for d in missing_func_dirs:
            print(f"  {d}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix BIDS events file formatting for MRAUT task.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fix a single file (output: <name>_fixed.tsv next to input)
  python fix_events_format.py sub-01_task-MRAUT_events.tsv

  # Fix and write to a specific output file
  python fix_events_format.py sub-01_task-MRAUT_events.tsv out_events.tsv

  # Batch: fix all *_events.tsv in source_folder and copy into the correct
  #   BIDS sub/ses/func paths under bids_root (auto-parsed from filenames)
  python fix_events_format.py --folder ./raw_events --bids /data/BIDS

  # Specify task and session explicitly
    python fix_events_format.py --folder ./raw_events --bids /data/BIDS --task crom --source-task MRAUT --ses 1

  # Include a run index in the output filename
  python fix_events_format.py --folder ./raw_events --bids /data/BIDS --task crom --ses 1 --run 1

  # Dry-run preview with backup
  python fix_events_format.py --folder ./raw_events --bids /data/BIDS --task crom --ses 1 --backup --dry-run

  # Legacy: fix into a single already-known func folder
  python fix_events_format.py --folder ./raw_events --dest /data/BIDS/sub-01/ses-1/func
"""
    )

    parser.add_argument('input', nargs='?', help='Input events TSV file (single-file mode)')
    parser.add_argument('output', nargs='?', help='Output events TSV file (single-file mode, optional)')
    parser.add_argument('--folder', metavar='SOURCE', help='Source folder containing *_events.tsv files')
    parser.add_argument('--bids', metavar='BIDS_ROOT',
                        help='BIDS dataset root; sub/ses paths are auto-constructed from filenames')
    parser.add_argument('--dest', metavar='FUNC_DIR',
                        help='Explicit BIDS func folder (legacy single-subject mode)')
    parser.add_argument('--task', metavar='TASK',
                        help='Task label for output filename (e.g. crom). '
                             'Skips bold-file matching; use when source files '
                             'have a different task name than the BIDS bold files.')
    parser.add_argument('--source-task', metavar='SOURCE_TASK',
                        help='Filter source files by task label parsed from filename '
                            '(e.g. MRAUT). Required when source folder contains '
                            'multiple tasks and --task is used.')
    parser.add_argument('--ses', metavar='SES',
                        help='Session label override (e.g. 1). '
                             'Overrides the session parsed from the source filename.')
    parser.add_argument('--run', metavar='RUN',
                        help='Run index to include in output filename (e.g. 1). '
                             'Inserted after task label: sub-X_ses-Y_task-Z_run-1_events.tsv')
    parser.add_argument('--excel-dir', metavar='EXCEL_DIR',
                        help='Directory containing subject-matched .xlsx item metadata files. '
                             'Defaults to the script directory.')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing output files even if content is identical.')
    parser.add_argument('--backup', action='store_true',
                        help='Back up existing events files before overwriting (implies --force).')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without writing any files')

    args = parser.parse_args()

    if args.folder:
        force = args.force or args.backup  # --backup implies overwrite
        if args.bids:
            process_folder_to_bids(args.folder, args.bids, task=args.task,
                                   source_task=args.source_task,
                                   ses_override=args.ses, run=args.run,
                                   excel_dir=args.excel_dir,
                                   force=force, backup=args.backup, dry_run=args.dry_run)
        elif args.dest:
            process_folder(args.folder, args.dest, force=force, dry_run=args.dry_run, excel_dir=args.excel_dir)
        else:
            parser.error("--folder requires either --bids <bids_root> or --dest <func_dir>")
    elif args.input:
        result = fix_single_file(args.input, args.output, excel_dir=args.excel_dir)

        out = args.output
        if out is None:
            p = Path(args.input)
            out = p.parent / f"{p.stem}_fixed{p.suffix}"

        print(f"Fixed events file saved to: {out}")
        print("\nSample of fixed events (first 20 rows):")
        print(result.head(20).to_string())
        print("\n\nUnique trial_types:")
        print(result['trial_type'].unique())
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
