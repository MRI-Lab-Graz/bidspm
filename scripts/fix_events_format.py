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
from pathlib import Path
from glob import glob


def fix_events_dataframe(df):
    """Fix the events dataframe formatting."""
    
    # Create output dataframe
    new_rows = []
    
    i = 0
    while i < len(df):
        row = df.iloc[i]
        
        event_type = str(row['event_type'])
        trial_type = str(row['trial_type'])
        onset = float(row['onset'])
        duration = row['duration']
        response_time = row['response_time']
        
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
            kb_event = {
                'onset': onset,
                'duration': 0,
                'trial_type': 'button_press',
                'item': 'n/a',
                'rating': 'n/a',
                'rating_type': 'n/a',
                'button_type': trial_type.replace('_key', ''),
                'response_time': 'n/a'
            }
            new_rows.append(kb_event)
            i += 1
            continue
        
        # Skip Keyboard rows that are part of a pair (they'll be processed with their pair)
        if event_type == 'Keyboard':
            i += 1
            continue
        
        # Initialize new event
        new_event = {
            'onset': onset,
            'duration': duration,
            'trial_type': 'n/a',
            'item': 'n/a',
            'rating': 'n/a',
            'rating_type': 'n/a',
            'button_type': 'n/a',
            'response_time': response_time if response_time != 'n/a' and pd.notna(response_time) else 'n/a'
        }
        
        # === FIXATION ===
        if event_type == 'TextStim' and trial_type == 'fixation':
            new_event['trial_type'] = 'fixation'
        
        # === ITEM presentation (AUTitem Krawatte) ===
        elif event_type.startswith('AUTitem '):
            item_name = event_type.replace('AUTitem ', '')
            new_event['trial_type'] = 'item'
            new_event['item'] = item_name
        
        # === VERBAL RESPONSE (response2 Krawatte) ===
        elif event_type == 'AUTresponse':
            response_match = re.match(r'response\d*\s+(.+)', trial_type)
            if response_match:
                new_event['item'] = response_match.group(1)
            new_event['trial_type'] = 'verbal_response'
        
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
            kb_response_time = keyboard_row['response_time']
            kb_trial_type = str(keyboard_row['trial_type'])
            
            # Calculate new onset: original onset + response_time from keyboard row
            if kb_response_time != 'n/a' and pd.notna(kb_response_time):
                new_onset = onset + float(kb_response_time)
            else:
                new_onset = onset
            
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
            
            kb_event = {
                'onset': round(new_onset, 4),
                'duration': 0,
                'trial_type': 'button_press',
                'item': 'n/a',
                'rating': 'n/a',
                'rating_type': 'n/a',
                'button_type': button_type,
                'response_time': 'n/a'
            }
            new_rows.append(kb_event)
            
            # Skip the keyboard row
            i += 1
        
        i += 1
    
    # Create output dataframe with column order
    columns = ['onset', 'duration', 'trial_type', 'item', 'rating', 'rating_type', 'button_type', 'response_time']
    result_df = pd.DataFrame(new_rows, columns=columns)
    
    # Sort by onset
    result_df = result_df.sort_values('onset').reset_index(drop=True)
    
    # Clean up n/a values
    result_df = result_df.fillna('n/a')
    
    return result_df


def fix_single_file(input_path, output_path=None):
    """Fix a single events file."""
    df = pd.read_csv(input_path, sep='\t')
    result_df = fix_events_dataframe(df)
    
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


def find_matching_bold(events_file, bids_func_folder):
    """Find the matching bold file for an events file based on sub/ses."""
    events_entities = parse_bids_filename(events_file.name)
    
    sub = events_entities.get('sub')
    ses = events_entities.get('ses')
    
    if not sub:
        return None
    
    # Build search pattern
    if ses:
        pattern = f"sub-{sub}_ses-{ses}_task-*_bold.nii*"
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


def process_folder(source_folder, dest_folder, dry_run=False):
    """
    Process all events files in source folder and copy to dest folder with BIDS naming.
    
    Args:
        source_folder: Folder containing source events TSV files
        dest_folder: BIDS func folder containing bold files (used for naming)
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
            print(f"  [DRY RUN] Would create: {output_path}")
        else:
            # Read, fix, and save
            try:
                df = pd.read_csv(events_file, sep='\t')
                result_df = fix_events_dataframe(df)
                result_df.to_csv(output_path, sep='\t', index=False)
                print(f"  Created: {output_path}")
                processed += 1
            except Exception as e:
                print(f"  ERROR: {e}")
    
    print("-" * 60)
    print(f"Processed {processed} file(s)")


def main():
    if len(sys.argv) < 2:
        print("""
Usage: 
  Single file:
    python fix_events_format.py <input_events.tsv> [output_events.tsv]
  
  Batch folder:
    python fix_events_format.py --folder <source_folder> <bids_func_folder> [--dry-run]

Examples:
  python fix_events_format.py sub-01_task-MRAUT_events.tsv
  python fix_events_format.py --folder ./raw_events ./bids/sub-01/ses-1/func
  python fix_events_format.py --folder ./raw_events ./bids/sub-01/ses-1/func --dry-run
""")
        sys.exit(1)
    
    # Check for folder mode
    if sys.argv[1] == '--folder':
        if len(sys.argv) < 4:
            print("Error: --folder requires <source_folder> and <bids_func_folder>")
            sys.exit(1)
        
        source_folder = sys.argv[2]
        dest_folder = sys.argv[3]
        dry_run = '--dry-run' in sys.argv
        
        process_folder(source_folder, dest_folder, dry_run)
    else:
        # Single file mode
        input_path = sys.argv[1]
        output_path = sys.argv[2] if len(sys.argv) > 2 else None
        
        result = fix_single_file(input_path, output_path)
        
        if output_path is None:
            p = Path(input_path)
            output_path = p.parent / f"{p.stem}_fixed{p.suffix}"
        
        print(f"Fixed events file saved to: {output_path}")
        print("\nSample of fixed events (first 20 rows):")
        print(result.head(20).to_string())
        print("\n\nUnique trial_types:")
        print(result['trial_type'].unique())


if __name__ == '__main__':
    main()
