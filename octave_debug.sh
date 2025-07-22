#!/bin/bash

# Octave-specific debugging
echo "🔬 Octave-MATLAB Path Debugging"
echo "==============================="

CONTAINER_PATH="/data/local/container/bidspm/bidspm_latest.sif"

echo "1. Testing raw file access in Octave..."
apptainer exec \
    --containall \
    --cleanenv \
    "$CONTAINER_PATH" \
    octave --eval "
    % Direct file check
    file_path = '/home/neuro/bidspm/lib/CPP_ROI/atlas/returnAtlasDir.m';
    if exist(file_path, 'file')
        fprintf('✅ File exists at: %s\n', file_path);
    else
        fprintf('❌ File does not exist at: %s\n', file_path);
    end
    
    % Check if we can read it
    try
        fid = fopen(file_path, 'r');
        if fid > 0
            first_line = fgetl(fid);
            fclose(fid);
            fprintf('✅ File readable, first line: %s\n', first_line);
        else
            fprintf('❌ Cannot open file\n');
        end
    catch
        fprintf('❌ Error reading file\n');
    end
    "

echo ""
echo "2. Testing path configuration step by step..."
apptainer exec \
    --containall \
    --cleanenv \
    "$CONTAINER_PATH" \
    octave --eval "
    fprintf('=== Step-by-step path debugging ===\n');
    
    % Show current path
    fprintf('Initial path:\n');
    initial_path = path();
    fprintf('%s\n', initial_path);
    
    % Add the atlas directory explicitly
    atlas_dir = '/home/neuro/bidspm/lib/CPP_ROI/atlas';
    fprintf('Adding atlas directory: %s\n', atlas_dir);
    addpath(atlas_dir);
    
    % Check if directory is in path now
    new_path = path();
    if contains(new_path, atlas_dir)
        fprintf('✅ Atlas directory added to path\n');
    else
        fprintf('❌ Atlas directory NOT in path\n');
    end
    
    % Test function again
    if exist('returnAtlasDir', 'file') == 2
        fprintf('✅ returnAtlasDir found after explicit addpath\n');
    else
        fprintf('❌ returnAtlasDir still not found\n');
        
        % List all .m files in atlas directory
        fprintf('Files in atlas directory:\n');
        files = dir(fullfile(atlas_dir, '*.m'));
        for i = 1:length(files)
            fprintf('  %s\n', files(i).name);
        end
    end
    "

echo ""
echo "3. Testing with explicit function call..."
apptainer exec \
    --containall \
    --cleanenv \
    "$CONTAINER_PATH" \
    octave --eval "
    addpath('/home/neuro/bidspm/lib/CPP_ROI/atlas');
    
    % Try to run the function directly from file
    try
        run('/home/neuro/bidspm/lib/CPP_ROI/atlas/returnAtlasDir.m');
        fprintf('✅ Function file executed successfully\n');
    catch ME
        fprintf('❌ Error executing function file: %s\n', ME.message);
    end
    
    % Try alternative function call
    try
        result = feval('returnAtlasDir');
        fprintf('✅ Function call successful: %s\n', result);
    catch ME
        fprintf('❌ Function call failed: %s\n', ME.message);
    end
    "

echo ""
echo "4. Final test: Bypassing Octave function discovery..."
echo "   Testing if we can patch the issue by copying the function..."
