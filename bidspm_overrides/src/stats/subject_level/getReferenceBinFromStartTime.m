function refBin = getReferenceBinFromStartTime(BIDS, filter, repetitionTime, nbTimeBins)
  %
  % Time-bin to use as SPM's ``fmri_t0`` for data that fMRIPrep already slice-time corrected.
  %
  % fMRIPrep drops ``SliceTiming`` after correcting and records ``SliceTimingCorrected`` and
  % ``StartTime`` (the time, in seconds, the data were shifted to). SPM samples the regressors at
  % ``(fmri_t0 - 1) * TR / fmri_t``, so the matching bin is ``round(StartTime / TR * fmri_t) + 1``.
  %
  % Returns [] unless every run is slice-time corrected and they all share one StartTime, in which
  % case the caller keeps its default (middle of the TR).
  %
  % USAGE::
  %
  %   refBin = getReferenceBinFromStartTime(BIDS, filter, repetitionTime, nbTimeBins)
  %

  % (C) Copyright 2026 bidspm developers

  refBin = [];

  warning('OFF', 'query:unknowMetadata');
  cleanup = onCleanup(@() warning('ON', 'query:unknowMetadata'));

  filter.target = 'SliceTimingCorrected';
  corrected = asCell(bids.query(BIDS, 'metadata', filter));
  if isempty(corrected) || ~all(cellfun(@(x) ~isempty(x) && all(logical(x)), corrected))
    return
  end

  filter.target = 'StartTime';
  startTime = asCell(bids.query(BIDS, 'metadata', filter));
  if isempty(startTime) || any(cellfun('isempty', startTime))
    return
  end

  startTime = cellfun(@(x) x(1), startTime);
  if max(abs(startTime - startTime(1))) > 1e-6
    return
  end

  refBin = round(startTime(1) / repetitionTime * nbTimeBins) + 1;

end

function value = asCell(value)
  if isempty(value)
    value = {};
  elseif ~iscell(value)
    value = {value};
  end
end
