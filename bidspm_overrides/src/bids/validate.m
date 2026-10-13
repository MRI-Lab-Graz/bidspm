function validate(args)
  %
  % Validate bids dataset.
  %
  % Upstream also shells out to ``validate_model`` for stats actions; that tool
  % crashes on pydantic 2 and rejects ``Transformer: bidspm`` models, so model
  % validation is done by the GUI (lib.core.validate_bids_model) instead.
  %

  % (C) Copyright 2022 bidspm developers
  if args.Results.skip_validation
    return
  end

  % run validation if validators are installed locally

  msg = sprintf('Validating bids dataset:\n %s', ...
                bids.internal.format_path(args.Results.bids_dir));
  logger('INFO', msg);

  [sts_data, msg_data] = bids.validate(args.Results.bids_dir);
  if sts_data == 1 && ~bids.internal.starts_with(msg_data, 'Require')
    msg_data = sprintf('\nBIDS validation of %s failed:\n\n%s\n\nCheck with:\n %s\n\n', ...
                       args.Results.bids_dir, ...
                       msg_data, ...
                       'https://bids-standard.github.io/bids-validator/');
    id = 'invalidBidsDataset';
    logger('ERROR', msg_data, 'filename', mfilename(), 'id', id);
  elseif args.Results.verbosity > 0
    disp(msg_data);
  end

end
