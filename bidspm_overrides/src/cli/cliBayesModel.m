function cliBayesModel(varargin)
  % Run stats on bids datasets.
  %
  % Type ``bidspm help`` for more info.
  %

  % TODO make sure that options defined in JSON or passed as a structure
  % overrides any other arguments

  % (C) Copyright 2023 bidspm developers
  args = inputParserForBayesModel();
  try
    parse(args, varargin{:});
  catch ME
    displayArguments(varargin{:});
    rethrow(ME);
  end

  validate(args);

  action = args.Results.action;
  opt = getOptionsFromCliArgument(args);
  opt.pipeline.type = 'stats';
  opt.pipeline.isBms = true;
  opt = checkOptions(opt);

  saveOptions(opt);

  % container v4.0.0 bug: bidsModelSelection's own inputParser registers
  % 'action' via addOptional (positional), not addParameter (name-value).
  % GNU Octave's inputParser enforces this strictly and errors with
  % "argument 'ACTION' is not a valid parameter" when called as
  % bidsModelSelection(opt, 'action', <value>) -- MATLAB's inputParser is
  % more lenient and accepts it, which is presumably how this shipped
  % unnoticed. Call positionally instead, which works on both.
  switch action
    case 'bms'
      bidsModelSelection(opt, 'all');
    case 'bms-posterior'
      bidsModelSelection(opt, 'posterior');
    case 'bms-bms'
      bidsModelSelection(opt, 'BMS');
  end

end
