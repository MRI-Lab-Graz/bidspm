function atlasDir = returnAtlasDir(atlas)
  %
  % USAGE::
  %
  %   atlasDir = returnAtlasDir(atlas)
  %
  % :parameter atlas: atlas to use (``''``, ``aal``, ``wang``, ``anatomy_toobox``,
  %                   ``neuromorphometrics``, ``visfatlas``, ``hcpex``, ``glasser``)
  % :type atlas: string
  %
  % spm-bids-runner ships no atlas (licences, see docs/third-party-licenses.md): a named atlas whose
  % files are not in the image is an error that says so, instead of a failure deep inside the caller.
  %
  % (C) Copyright 2021 CPP ROI developers

  atlasDir = fileparts(mfilename('fullpath'));

  if nargin > 0

    required = '';

    switch lower(atlas)

      case 'aal'
        atlasDir = fullfile(atlasDir, 'AAL3');

      case 'wang'
        atlasDir = fullfile(atlasDir, 'visual_topography_probability_atlas');

      case 'anatomy_toobox'
        atlasDir = fullfile(spm('dir'), 'toolbox', 'Anatomy');

      case 'visfatlas'
        atlasDir = fullfile(atlasDir, 'visfAtlas');

      case 'hcpex'
        atlasDir = fullfile(atlasDir, 'HCPex', 'HCPex_v1.0');

      case 'glasser'
        atlasDir = fullfile(atlasDir, 'Glasser');

      case 'neuromorphometrics'
        required = fullfile(spm('dir'), 'tpm', 'labels_Neuromorphometrics.nii');

      otherwise
        error('unknown atlas type');
    end

    if isempty(required)
      present = exist(atlasDir, 'dir') == 7;
      required = atlasDir;
    else
      present = exist(required, 'file') == 2;
    end

    if ~present
      error('returnAtlasDir:atlasMissing', ...
            ['Atlas "%s" is not included in this image (spm-bids-runner ships no atlases, ' ...
             'for licence reasons). To use it, build a derived image that adds your own copy at ' ...
             '%s (see README, "Atlases").'], atlas, required);
    end

  end

  atlasDir = spm_file(atlasDir, 'cpath');

end
