function checkRegressorName(SPM)
  %
  % extra checks for ``bidsModelSelection`` to make sure that:
  %
  % - all sessions can be vertically concatenated
  % - after concatenation all regressors have the same name (or that there are dummy regressors)
  %
  % USAGE::
  %
  %  checkRegressorName(SPM)
  %
  %
  % See also: bidsModelSelection
  %

  % (C) Copyright 2022 bidspm developers

  all_columns = {};

  for i_session = 1:numel(SPM.Sess)

    % container v4.0.0 bug: SPM.Sess(i_session).U is [] (not a 0x0 struct)
    % for constant/intercept-only models (no HRF-convolved conditions), so
    % `.name` on it throws "matrix cannot be indexed with ." instead of
    % just yielding zero regressors.
    %
    % container v4.0.0 bug (2): for conditions with parametric modulators,
    % SPM.Sess(i_session).U(k).name is a cell array of several names (main
    % condition + one per modulator, e.g. {'item', 'itemxai_rating_mod^1',
    % 'itemxai_rating_mod^2'}) instead of a scalar char like every other
    % condition. cat(1, ...U.name) requires uniform shape/length across all
    % U(k), so it throws "cat: dimension mismatch" as soon as one condition
    % has modulators and another doesn't (or they have differing name
    % lengths). Build the flat name list explicitly instead so both scalar
    % and multi-name conditions are handled the same way.
    regressors = {};
    for iU = 1:numel(SPM.Sess(i_session).U)
      name = SPM.Sess(i_session).U(iU).name;
      if ischar(name)
        name = {name};
      end
      regressors = [regressors, name(:)']; %#ok<AGROW>
    end
    confounds = SPM.Sess(i_session).C.name;

    all_columns(i_session, :) = cat(2, regressors, confounds);

  end

  for i_col = 1:size(all_columns, 2)
    nbRegressorInThisCol = numel(unique(all_columns(:, i_col)));
    assert(nbRegressorInThisCol <= 2);
    if nbRegressorInThisCol > 2 || ...
      (nbRegressorInThisCol == 2 && ...
       ~any(ismember({'dummyRegressor', 'dummyConfound'}, all_columns(:, i_col))))
      disp(all_columns(:, i_col));
      error('Different regressors in the same column.');
    end
  end

end
