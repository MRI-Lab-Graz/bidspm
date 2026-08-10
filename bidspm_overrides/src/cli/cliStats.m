function cliStats(varargin)
  % Run stats on bids datasets.
  %
  % Type ``bidspm help`` for more info.
  %

  % TODO make sure that options defined in JSON or passed as a structure
  % overrides any other arguments

  % (C) Copyright 2023 bidspm developers
  args = inputParserForStats();
  parse(args, varargin{:});

  validate(args);

  action = args.Results.action;
  analysisLevel = args.Results.analysis_level;
  nodeName = args.Results.node_name;
  concatenate = args.Results.concatenate;

  isSubjectLevel = strcmp(analysisLevel, 'subject');
  specify_only = strcmp(action, 'specify_only');
  estimate = strcmp(action, 'stats');
  contrasts = ismember(action, {'stats', 'contrasts'});
  results = ismember(action, {'stats', 'contrasts', 'results'});

  if specify_only
    estimate = false;
  end

  opt = getOptionsFromCliArgument(args);

  % Apply confound-strategy suffix to node names when --name_by_confounds is
  % set.  addConfoundsToDesignMatrix(… 'updateName', true) appends the
  % strategy string to each root-node Name so each strategy writes to a
  % distinct _node-<Name> output folder instead of silently overwriting.
  if isfield(args.Results, 'name_by_confounds') && args.Results.name_by_confounds
    allModels = cellstr(opt.model.file);
    for iM = 1:numel(allModels)
      bm = BidsModel('file', allModels{iM});
      bm = bm.addConfoundsToDesignMatrix('updateName', true);
      [~, fname, ~] = fileparts(allModels{iM});
      tmpFile = fullfile(tempdir(), [fname '_confounds_named.json']);
      bids.util.jsonencode(bm.content, tmpFile);
      allModels{iM} = tmpFile;
    end
    opt.model.file = allModels;
  end

  if opt.glm.roibased.do
    opt.bidsFilterFile.roi.space = opt.space;
    opt.bidsFilterFile.roi.label = opt.roi.name;
  end

  opt.pipeline.type = 'stats';

  if opt.model.designOnly
    contrasts = false;
    results = false;
  end

  allModels = cellstr(opt.model.file);

  for iModel = 1:numel(allModels)

    if isfield(opt, 'model')
      opt = rmfield(opt, 'model');
    end
    opt.model.file = allModels{iModel};

    opt = checkOptions(opt);

    saveOptions(opt);

    boilerplate(opt, ...
                'outputPath', fullfile(opt.dir.output, 'reports'), ...
                'pipelineType', 'stats', ...
                'verbosity', 0);
    if opt.boilerplateOnly
      continue
    end

    if opt.glm.roibased.do
      bidsFFX('specify', opt);
      if ~opt.model.designOnly
        bidsRoiBasedGLM(opt);
      end

    else

      if isSubjectLevel && ...
              (specify_only || ...
               estimate && opt.model.designOnly)
        bidsFFX('specify', opt);
        compileScrubbingStats(opt.dir.stats);
      end

      if estimate
        runEstimate(isSubjectLevel, opt, nodeName);
      end

      if contrasts
        runContrasts(isSubjectLevel, opt, nodeName, concatenate);
      end

      if results
        bidsResults(opt, ...
                    'nodeName', nodeName, ...
                    'analysisLevel', analysisLevel);
      end

    end

  end

end

function runEstimate(isSubjectLevel, opt, nodeName)
  if isSubjectLevel

    if opt.glm.concatenateRuns
      bidsFFX('specify', opt);
      compileScrubbingStats(opt.dir.stats);
      bidsFFX('estimate', opt);

    else
      bidsFFX('specifyAndEstimate', opt);
      compileScrubbingStats(opt.dir.stats);
    end

  else

    if opt.fwhm.contrast > 0
      bidsSmoothContrasts(opt);
    end

    bidsRFX('RFX', opt, 'nodeName', nodeName);

  end
end

function runContrasts(isSubjectLevel, opt, nodeName, concatenate)
  if isSubjectLevel
    bidsFFX('contrasts', opt);
  else
    bidsRFX('contrasts', opt, 'nodeName', nodeName);
  end

  if isSubjectLevel && concatenate
    bidsConcatBetaTmaps(opt);
  end
end
