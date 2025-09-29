% Octave startup script for BIDSPM local execution
warning('off', 'all');

project_root = getenv('BIDSPM_PROJECT_ROOT');
if isempty(project_root)
    project_root = pwd;
end

spm12_path = fullfile(project_root, 'external', 'spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 added to path\n');
else
    fprintf('Warning: SPM12 path not found at %s\n', spm12_path);
end

bidspm_path = fullfile(project_root, 'local_src', 'bidspm_local');
if exist(bidspm_path, 'dir')
    addpath(bidspm_path);
    addpath(fullfile(bidspm_path, 'src'));
    addpath(genpath(fullfile(bidspm_path, 'lib')));
    fprintf('BIDSPM added to path\n');
else
    fprintf('Warning: BIDSPM path not found at %s\n', bidspm_path);
end

if exist('spm', 'file')
    try
        spm('defaults', 'fmri');
        spm_jobman('initcfg');
        fprintf('SPM initialised\n');
    catch ME
        fprintf('Warning: SPM initialisation failed (%s)\n', ME.message);
    end
end

fprintf('Octave startup complete\n');
