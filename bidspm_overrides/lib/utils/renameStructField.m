function s = renameStructField(s, oldName, newName)
  %
  % Renames field oldName of struct (array) s to newName, keeping the field order.
  % An existing field newName is overwritten. A missing oldName is a no-op.
  %
  % USAGE::
  %
  %   s = renameStructField(s, oldName, newName)
  %
  % Own implementation for spm-bids-runner (GPL-3.0, like bidspm); it replaces a helper
  % without a licence that upstream bidspm v4.0.0 bundles in lib/utils.

  if strcmp(oldName, newName) || ~isfield(s, oldName)
    return
  end

  names = fieldnames(s);
  names(strcmp(names, newName)) = [];
  names{strcmp(names, oldName)} = newName;

  [s.(newName)] = s.(oldName);
  s = orderfields(rmfield(s, oldName), names);

end
