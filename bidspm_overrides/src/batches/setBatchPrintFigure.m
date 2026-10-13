function matlabbatch = setBatchPrintFigure(matlabbatch, opt, figureName) %#ok<INUSD>
  %
  % No-op: SPM's "Print figure" job needs a graphics toolkit, which the
  % container does not have, so upstream's job only ever logged
  % "Print error: Figure not found." on every subject.
  %
  % USAGE::
  %
  %   matlabbatch = setBatchPrintFigure(matlabbatch, opt, figureName)
  %

  % (C) Copyright 2020 bidspm developers

end
