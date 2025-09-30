% Minimal Octave startup script for BIDSPM (no full initialization)
warning('off', 'all');

% Add SPM12 to path
spm12_path = fullfile(pwd, 'external/spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
end

% Add BIDSPM to path (minimal setup)
bidspm_path = fullfile(pwd, 'local_src/bidspm_local');
if exist(bidspm_path, 'dir')
    addpath(bidspm_path);
    addpath(fullfile(bidspm_path, 'src'));
    addpath(genpath(fullfile(bidspm_path, 'lib')));
end

% Add SPM to MATLAB/Octave startup
if exist('spm_defaults', 'file')
    spm_defaults;
end
