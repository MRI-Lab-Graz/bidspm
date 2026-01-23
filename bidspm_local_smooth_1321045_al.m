
% BIDSPM Local Execution Script for Smoothing
% HPC-compatible setup with SPM12 and BIDSPM paths

% Set warning level to reduce verbose output
warning('off', 'all');

% Add SPM12 standalone if available
spm12_path = fullfile(pwd, 'external/spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 standalone added to path\n');
end

% Add BIDSPM to path and initialize
bidspm_path = '/data/local/software/bidspm/local_src/bidspm_local';
if exist(bidspm_path, 'dir')
    addpath(bidspm_path);
    fprintf('Initializing BIDSPM from: %s\n', bidspm_path);
    % Initialize BIDSPM (this will load necessary packages like statistics, datatypes)
    if exist('bidspm', 'file')
        bidspm('init');
    end
end

% Try to initialize SPM if available
try
    if exist('spm', 'file')
        spm('defaults', 'fmri');
        spm_jobman('initcfg');
        fprintf('SPM initialized successfully\n');
    end
catch
    fprintf('SPM initialization skipped\n');
end

try
    bidspm('/data/local/132/derivatives/fmriprep', ...
           '/data/local/132/derivatives', ...
           'subject', ...
           'action', 'smooth', ...
           'participant_label', {'1321045'}, ...
           'task', {'al'}, ...
           'space', {'MNI152NLin2009cAsym'}, ...
           'fwhm', 8, ...
           'verbosity', 1);
    fprintf('✅ Smoothing completed successfully\n');
    exit(0);
catch ME
    fprintf('❌ Error during smoothing: %s\n', ME.message);
    exit(1);
end
