
% BIDSPM Local Execution Script - smooth
warning('off', 'all');

% Add paths
spm12_path = fullfile(pwd, 'external/spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
end

bidspm_path = '/data/local/software/bidspm/local_src/bidspm_local';
if exist(bidspm_path, 'dir')
    addpath(bidspm_path);
    if exist('bidspm', 'file')
        bidspm('init');
    end
end

try
    if exist('spm', 'file')
        spm('defaults', 'fmri');
        spm_jobman('initcfg');
    end
catch
end

try

    bidspm('/data/local/141/derivatives/fmriprep', ...
           '/data/local/141/derivatives', ...
           'subject', ...
           'action', 'smooth', ...
           'participant_label', {'141U802Z'}, ...
           'task', {'crom'}, ...
           'space', {'MNI152NLin2009cAsym'}, ...
           'fwhm', 6, ...
           'verbosity', 2);
    fprintf('Smoothing completed successfully\n');
    exit(0);

catch ME
    fprintf('Error: %s\n', ME.message);
    exit(1);
end
