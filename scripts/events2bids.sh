#!/bin/bash

# Function to print header with terminal artwork
print_header() {
    echo -e "\033[1;32m"  # Set color to green
    echo "==================================================="
    echo "                     MRI - LAB GRAZ"
    echo "==================================================="
    echo -e "\033[0m"  # Reset to default color
    echo "Date: $(date '+%Y-%m-%d')"
    echo "Time: $(date +%H:%M)"
    echo "---------------------------------------------------"
}

# Function to backup existing files
backup_existing_files() {
    local target_dir="$1"
    local file_pattern="$2"
    local backup_type="$3"
    
    # Create timestamp for backup directory
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_dir="$target_dir/backup_${backup_type}_${timestamp}"
    
    # Check if any files matching the pattern exist
    local files_found=false
    for existing_file in "$target_dir"/$file_pattern; do
        if [ -f "$existing_file" ]; then
            files_found=true
            break
        fi
    done
    
    if [ "$files_found" = true ]; then
        # Create backup directory
        mkdir -p "$backup_dir"
        echo "Creating backup directory: $backup_dir"
        
        # Move existing files to backup
        for existing_file in "$target_dir"/$file_pattern; do
            if [ -f "$existing_file" ]; then
                echo "  Backing up: $(basename "$existing_file")"
                mv "$existing_file" "$backup_dir/"
            fi
        done
        echo "  Backup completed for $target_dir"
    fi
}

# Initialize variables for source_dir, bids_root_dir, file_type, and backup
source_dir=""
bids_root_dir=""
file_type=""
backup_flag=false

# Print the header
print_header

# Process command-line options using while loop and case statement
while [[ $# -gt 0 ]]; do
    key="$1"

    case $key in
        -e|--events)
            source_dir="$2"
            shift # past argument
            shift # past value
            ;;
        -b|--bids)
            bids_root_dir="$2"
            shift # past argument
            shift # past value
            ;;
        -t|--type)
            file_type="$2"
            shift # past argument
            shift # past value
            ;;
        --backup)
            backup_flag=true
            shift # past argument
            ;;
        *)    # unknown option
            echo "Usage: $0 -e /path/to/source -b /path/to/BIDS -t events|physio [--backup]"
            exit 1
            ;;
    esac
done

# Check if the source and BIDS root directories and file_type are set
if [ -z "$source_dir" ] || [ -z "$bids_root_dir" ] || [ -z "$file_type" ]; then
    echo "Error: Source directory, BIDS root directory, and file type must be specified."
    echo "Usage: $0 -e /path/to/source -b /path/to/BIDS -t events|physio [--backup]"
    exit 1
fi

# Check if file_type is valid
if [ "$file_type" != "events" ] && [ "$file_type" != "physio" ]; then
    echo "Error: File type must be either 'events' or 'physio'."
    exit 1
fi

# Check if the source and BIDS root directories exist
if [ ! -d "$source_dir" ] || [ ! -d "$bids_root_dir" ]; then
    echo "Error: Check that both the source directory ($source_dir) and the BIDS root directory ($bids_root_dir) exist."
    exit 1
fi

# Process files based on file_type
if [ "$file_type" == "events" ]; then
    # Loop over each event file in the source directory
    for file in "$source_dir"/*_events.tsv; do
        # Check if file exists (in case no files match the pattern)
        if [ ! -f "$file" ]; then
            echo "No events files found in $source_dir"
            exit 1
        fi

        # Extract the base filename without the path
        base_filename=$(basename "$file")

        # Check if the events file has 5 lines or fewer
        line_count=$(wc -l < "$file")
        if [ "$line_count" -le 5 ]; then
            echo "Warning: Events file seems to be too small, please check your data - $file"
            continue  # Skip to the next file or add additional handling as needed
        fi

        # Parse necessary components from the filename
        sub=$(echo "$base_filename" | grep -o 'sub-[^_]*')
        ses=$(echo "$base_filename" | grep -o 'ses-[^_]*')

        # Construct the target directory path
        target_dir="$bids_root_dir/$sub/$ses/func"

        # Check if the expected BIDS structure exists
        if [ ! -d "$target_dir" ]; then
            echo "Warning: Target directory structure ($target_dir) does not exist. File will still be copied, but please verify structure."
            mkdir -p "$target_dir"
        fi

        # Backup existing events files if backup flag is set
        if [ "$backup_flag" = true ]; then
            backup_existing_files "$target_dir" "*_events.tsv" "events"
        fi

        # Copy the file to the target directory
        echo "Copying: $base_filename -> $target_dir/"
        cp "$file" "$target_dir/"
    done

elif [ "$file_type" == "physio" ]; then
    # Loop over each physio file (tsv.gz) in the source directory
    for file in "$source_dir"/*_physio.tsv.gz; do
        # Check if file exists (in case no files match the pattern)
        if [ ! -f "$file" ]; then
            echo "No physio files found in $source_dir"
            exit 1
        fi

        # Extract the base filename without the extension
        base_filename=$(basename "$file" .tsv.gz)

        # Parse necessary components from the filename
        sub=$(echo "$base_filename" | grep -o 'sub-[^_]*')
        ses=$(echo "$base_filename" | grep -o 'ses-[^_]*')

        # Construct the target directory path
        target_dir="$bids_root_dir/$sub/$ses/func"

        # Check if the expected BIDS structure exists
        if [ ! -d "$target_dir" ]; then
            echo "Warning: Target directory structure ($target_dir) does not exist. Files will still be copied, but please verify structure."
            mkdir -p "$target_dir"
        fi

        # Backup existing physio files if backup flag is set
        if [ "$backup_flag" = true ]; then
            backup_existing_files "$target_dir" "*_physio.tsv.gz" "physio"
            backup_existing_files "$target_dir" "*_physio.json" "physio"
        fi

        # Copy both the tsv.gz and json files to the target directory
        tsv_gz_file="$file"
        json_file="$source_dir/$base_filename.json"

        # Check if JSON file exists
        if [ ! -f "$json_file" ]; then
            echo "Warning: Corresponding JSON file not found for $tsv_gz_file"
        else
            echo "Copying: $(basename "$json_file") -> $target_dir/"
            cp "$json_file" "$target_dir/"
        fi

        echo "Copying: $(basename "$tsv_gz_file") -> $target_dir/"
        cp "$tsv_gz_file" "$target_dir/"
    done
fi

echo "All files have been copied successfully."
if [ "$backup_flag" = true ]; then
    echo "Note: Any existing files were backed up to timestamped backup directories."
fi