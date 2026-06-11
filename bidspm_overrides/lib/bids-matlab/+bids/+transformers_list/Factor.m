function data = Factor(transformer, data)
  %
  % Converts nominal/categorical variable(s) to indicator (dummy-coded) columns.
  %
  % For a single Input column the output column names follow the BIDS Transforms
  % spec: <col>_<level>
  %
  % For multiple Input columns a cross-product is created:
  %   <col1>_<level1>_<col2>_<level2>_...
  %

  % (C) Copyright 2022 BIDS-MATLAB developers

  input = bids.transformers_list.get_input(transformer, data);

  % Collect valid inputs and their levels/values
  valid_cols  = {};
  all_levels  = {};
  all_values  = {};

  for i = 1:numel(input)
    col = input{i};
    if ~isfield(data, col)
      continue
    end

    raw = data.(col);

    if isnumeric(raw)
      vals = cellstr(num2str(raw(:)));
    elseif ischar(raw)
      vals = cellstr(raw);
    elseif iscell(raw)
      % Filter outputs {nan} for non-matching rows; convert to 'n/a' so we
      % have a clean cellstr that unique() can handle in Octave.
      non_str = ~cellfun(@ischar, raw);
      if any(non_str)
        raw(non_str) = {'n/a'};
      end
      vals = raw(:);
    else
      continue
    end

    data.(col) = vals;           % normalise to cellstr in-place
    lvls = unique(vals);
    valid_cols{end + 1} = col;   %#ok<AGROW>
    all_levels{end + 1} = lvls;  %#ok<AGROW>
    all_values{end + 1} = vals;  %#ok<AGROW>
  end

  if isempty(valid_cols)
    return
  end

  % Build all level-combinations (cartesian product across columns)
  n      = numel(valid_cols);
  sizes  = cellfun(@numel, all_levels);
  total  = prod(sizes);

  for k = 1:total
    % decode linear index k into per-column level indices
    tmp    = k - 1;
    idx    = zeros(1, n);
    stride = 1;
    for c = 1:n
      idx(c) = mod(floor(tmp / stride), sizes(c)) + 1;
      stride  = stride * sizes(c);
    end

    % build name: col1_level1_col2_level2_... (BIDS Transforms spec order)
    parts = {};
    for c = 1:n
      parts{end + 1} = valid_cols{c};           %#ok<AGROW>
      parts{end + 1} = all_levels{c}{idx(c)};   %#ok<AGROW>
    end
    field = strjoin(parts, '_');
    field = regexprep(field, '[^a-zA-Z0-9_]', '');

    % indicator: 1 where every column matches its chosen level
    indicator = true(size(all_values{1}));
    for c = 1:n
      indicator = indicator & strcmp(all_values{c}, all_levels{c}{idx(c)});
    end
    data.(field) = indicator;
  end

end
