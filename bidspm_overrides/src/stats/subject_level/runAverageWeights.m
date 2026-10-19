function w = runAverageWeights(SPM, regIdx)
  %
  % 1 / (number of runs) for each selected column, counted per condition: columns are grouped by their name
  % without the 'Sn(k) ' session prefix, so a glob contrast ('face*') averages each matched condition over
  % its own runs. A single run gives 1 everywhere (identical to upstream bidspm, which summed runs).
  %
  % USAGE::
  %
  %   C.C(end, regIdx) = weight * runAverageWeights(SPM, regIdx);
  %
  % (C) Copyright 2026 bidspm runner (local override, not upstream)

  if islogical(regIdx)
    regIdx = find(regIdx);
  end
  names = regexprep(SPM.xX.name(regIdx), '^Sn\(\d+\) ', '');
  [~, ~, group] = unique(names);
  counts = accumarray(group(:), 1);
  w = 1 ./ counts(group(:))';

end
