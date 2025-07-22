#!/bin/bash
echo "📡 Remote Octave Debug - Upload this to your HPC server and run it there"
echo "==============================================================="
echo ""
echo "# Upload this script to your HPC server and run:"
echo "# scp remote_octave_debug.sh user@yourserver:~/"
echo "# ssh user@yourserver"
echo "# chmod +x remote_octave_debug.sh"
echo "# ./remote_octave_debug.sh"
echo ""
echo "🔬 Octave-MATLAB Path Debugging"
echo "==============================="
echo ""
echo "1. Testing raw file access in Octave..."
apptainer exec container_apptainer_atlas_fix.json octave --eval "
    fprintf('\\n🔍 Testing direct file access...\\n');
    file_path = '/home/neuro/bidspm/lib/CPP_ROI/atlas/returnAtlasDir.m';
    if exist(file_path, 'file')
        fprintf('✅ File exists: %s\\n', file_path);
        % Try to read the first line
        fid = fopen(file_path, 'r');
        if fid > 0
            first_line = fgetl(fid);
            fprintf('📄 First line: %s\\n', first_line);
            fclose(fid);
        else
            fprintf('❌ Cannot open file for reading\\n');
        end
    else
        fprintf('❌ File does not exist: %s\\n', file_path);
    end
"

echo ""
echo "2. Testing path configuration step by step..."
apptainer exec container_apptainer_atlas_fix.json octave --eval "
    fprintf('\\n🛠️ MATLAB Path Configuration Test...\\n');
    
    % Show current path
    current_path = path();
    fprintf('📍 Current Octave path:\\n%s\\n\\n', current_path);
    
    % Add the atlas directory explicitly
    atlas_dir = '/home/neuro/bidspm/lib/CPP_ROI/atlas';
    addpath(atlas_dir);
    fprintf('✅ Added to path: %s\\n', atlas_dir);
    
    % Check if path was added
    new_path = path();
    if contains(new_path, atlas_dir)
        fprintf('✅ Atlas directory is in path\\n');
    else
        fprintf('❌ Atlas directory NOT in path\\n');
    end
    
    % Try to find the function
    which_result = which('returnAtlasDir');
    if isempty(which_result)
        fprintf('❌ returnAtlasDir not found with which()\\n');
    else
        fprintf('✅ returnAtlasDir found at: %s\\n', which_result);
    end
    
    % Try exist function
    exist_result = exist('returnAtlasDir', 'file');
    fprintf('🔍 exist() result: %d (2=M-file, 0=not found)\\n', exist_result);
"

echo ""
echo "3. Testing with explicit function call..."
apptainer exec container_apptainer_atlas_fix.json octave --eval "
    fprintf('\\n🎯 Direct Function Call Test...\\n');
    
    % First ensure the path is set
    addpath('/home/neuro/bidspm/lib/CPP_ROI/atlas');
    
    % Try different ways to call the function
    try
        fprintf('🧪 Attempting: returnAtlasDir()\\n');
        result = returnAtlasDir();
        fprintf('✅ SUCCESS: returnAtlasDir() returned: %s\\n', result);
    catch e
        fprintf('❌ FAILED: %s\\n', e.message);
        
        % Try loading the file directly
        try
            fprintf('🧪 Attempting: run(''/home/neuro/bidspm/lib/CPP_ROI/atlas/returnAtlasDir.m'')\\n');
            run('/home/neuro/bidspm/lib/CPP_ROI/atlas/returnAtlasDir.m');
            fprintf('✅ Direct run() succeeded\\n');
        catch e2
            fprintf('❌ Direct run() failed: %s\\n', e2.message);
        end
    end
"

echo ""
echo "4. Testing function content and syntax..."
apptainer exec container_apptainer_atlas_fix.json octave --eval "
    fprintf('\\n📖 Function Content Analysis...\\n');
    
    file_path = '/home/neuro/bidspm/lib/CPP_ROI/atlas/returnAtlasDir.m';
    
    % Read and display function content
    fid = fopen(file_path, 'r');
    if fid > 0
        fprintf('📄 Function content:\\n');
        line_num = 1;
        while ~feof(fid)
            line = fgetl(fid);
            if ischar(line)
                fprintf('%3d: %s\\n', line_num, line);
                line_num = line_num + 1;
                if line_num > 20  % Limit output
                    fprintf('... (truncated)\\n');
                    break;
                end
            end
        end
        fclose(fid);
    else
        fprintf('❌ Cannot read function file\\n');
    end
"

echo ""
echo "5. Final test: Environment and workaround..."
apptainer exec container_apptainer_atlas_fix.json octave --eval "
    fprintf('\\n🔧 Environment Analysis and Workaround Test...\\n');
    
    % Check Octave version
    fprintf('🐙 Octave version: %s\\n', version());
    
    % Check if this is actually MATLAB vs Octave issue
    fprintf('🔍 Environment: ');
    if exist('OCTAVE_VERSION', 'builtin')
        fprintf('Running in Octave\\n');
    else
        fprintf('Running in MATLAB\\n');
    end
    
    % Try creating a local copy of the function
    try
        atlas_dir = '/home/neuro/bidspm/lib/CPP_ROI/atlas';
        func_file = fullfile(atlas_dir, 'returnAtlasDir.m');
        
        % Read the function
        fid = fopen(func_file, 'r');
        if fid > 0
            func_content = fread(fid, '*char')';
            fclose(fid);
            
            % Write to current directory
            local_fid = fopen('/tmp/returnAtlasDir.m', 'w');
            if local_fid > 0
                fprintf(local_fid, '%s', func_content);
                fclose(local_fid);
                
                % Add tmp to path and try again
                addpath('/tmp');
                fprintf('✅ Copied function to /tmp and added to path\\n');
                
                % Test the copied function
                which_result = which('returnAtlasDir');
                if ~isempty(which_result)
                    fprintf('✅ Function now found at: %s\\n', which_result);
                    try
                        result = returnAtlasDir();
                        fprintf('🎉 SUCCESS with copied function: %s\\n', result);
                    catch e
                        fprintf('❌ Copied function still fails: %s\\n', e.message);
                    end
                else
                    fprintf('❌ Copied function still not found\\n');
                end
            else
                fprintf('❌ Cannot write to /tmp\\n');
            end
        else
            fprintf('❌ Cannot read original function\\n');
        end
    catch e
        fprintf('❌ Workaround failed: %s\\n', e.message);
    end
"
