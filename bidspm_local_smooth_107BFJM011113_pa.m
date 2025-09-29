
% BIDSPM Local Execution Script for Smoothing
% HPC-compatible setup with SPM12 and BIDSPM paths

% Configure local package installation directory to avoid disk space issues
if exist('pkg', 'builtin')
    pkg('prefix', fullfile(pwd, 'octave_packages'), fullfile(pwd, 'octave_packages'));
    fprintf('Octave package directory set to local folder\n');
end

% Add SPM12 standalone if available
spm12_path = fullfile(pwd, 'spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 standalone added to path\n');
end

% Add BIDSPM to path and initialize
addpath('/data/local/software/bidspm/bidspm_local');
bidspm('init');

try
    bidspm('/data/local/107_JM01/derivatives/fmriprep', ...
           '/data/local/107_JM01/derivatives', ...
           'subject', ...
           'action', 'smooth', ...
           'participant_label', {'107BFJM011113'}, ...
           'task', {'pa'}, ...
           'space', {'MNI152NLin2009cAsym'}, ...
           'fwhm', 8, ...
           'verbosity', 0);
    fprintf('✅ Smoothing completed successfully\n');
    exit(0);
catch ME
    fprintf('❌ Error during smoothing: %s\n', ME.message);
    exit(1);
end
