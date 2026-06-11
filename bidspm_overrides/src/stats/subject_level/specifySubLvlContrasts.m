function [contrasts, count] = specifySubLvlContrasts(model, node, contrasts, count)
  %
  %
  %
  % USAGE::
  %
  %   [contrasts, counter] = specifySubLvlContrasts(model, node, contrasts, counter)
  %
  % :param model:
  % :type  model: BidsModel instance
  %
  % :param contrasts:
  % :type  contrasts: struct
  %
  % :param node:
  % :type  node: struct
  %
  % :param counter:
  % :type  counter: integer
  %
  %
  % See also: specifyContrasts
  %

  % (C) Copyright 2022 bidspm developers

  if ~isfield(node, 'Contrasts')
    return
  end

  if ~strcmpi(node.Level, 'subject')
    return
  end

  % include contrasts that involve contrasting conditions
  % amongst themselves or inferior to baseline
  for iCon = 1:length(node.Contrasts)

    thisContrast = checkContrast(model, node, iCon);

    if isempty(thisContrast) || strcmp(thisContrast.Test, 'pass')
      continue
    end

    if isnumeric(node.Model.X) && node.Model.X == 1
      [contrasts, count] = averageAtSubjectLevel(model, ...
                                                 contrasts, ...
                                                 count, ...
                                                 thisContrast);

    elseif iscell(node.Model.X) && ...
            all(cellfun(@(x) strcmp(x, 'session') || x == 1, node.Model.X))
      [contrasts, count] = crossSesContrast(model, ...
                                            node, ...
                                            thisContrast, ...
                                            contrasts, ...
                                            count);

    else
      % Factor-derived run contrasts: ConditionList entries encode run and
      % parent contrast name, e.g. "run_1_contrast_Repeated_vs_Unrepeated".
      % Build the contrast vector by combining the parent contrast weights
      % with the per-run columns of the within-subject SPM.
      [contrasts, count] = crossRunContrast(model, ...
                                            node, ...
                                            thisContrast, ...
                                            contrasts, ...
                                            count);
    end

  end

end

function  [contrasts, count] = crossSesContrast(model, node, thisContrast, contrasts, count)
  % loop over contrasts from previous levels to do a cross session comparison
  sessionList = thisContrast.ConditionList;

  if ~strcmp(thisContrast.Test, 't')
    return
  end

  % collect contrasts from previous runs
  % TODO
  % dummyContrastsList = getDummyContrastFromParentNode(model, node);
  contrastsList = getContrastsFromParentNode(model, node);

  for iCon = 1:numel(contrastsList)

    contrastName = [thisContrast.Name '-' contrastsList{iCon}.Name];
    C = newContrast(model.SPM, contrastName, thisContrast.Test, sessionList);

    for iSes = 1:length(sessionList)
      % apply weight specified in previous level
      % multiplied by weight for each sessions
      for iCdt = 1:numel(contrastsList{iCon}.ConditionList)
        cdtName = contrastsList{iCon}.ConditionList{iCdt};
        [~, regIdx] = getRegressorIdx(cdtName, model.SPM, sessionList{iSes});
        C.C(end, regIdx) = contrastsList{iCon}.Weights(iCdt) * ...
            thisContrast.Weights(iSes);
      end
    end

    [contrasts, count] = appendContrast(contrasts, C, count, thisContrast.Test);

  end

end

function [contrasts, count] = averageAtSubjectLevel(model, contrasts, count, thisContrast)

  conditionList = thisContrast.ConditionList;

  C = newContrast(model.SPM, thisContrast.Name, thisContrast.Test, conditionList);

  row = 1;

  for iCdt = 1:length(conditionList)

    cdtName = conditionList{iCdt};
    if isempty(cdtName)
      continue
    end

    [~, regIdx, status] = getRegressorIdx(cdtName, model.SPM);
    if ~status
      break
    end

    regIdx = find(regIdx);

    % give them the value specified in the model
    if strcmp(thisContrast.Test, 't')
      C.C(end, regIdx) = thisContrast.Weights(iCdt);

    elseif strcmp(thisContrast.Test, 'F')

      for i = 1:numel(regIdx)
        for i_w = 1:size(thisContrast.Weights, 1)
          C.C(row, regIdx(i)) = thisContrast.Weights(i_w, iCdt);
          row = row + 1;
        end
      end

    end

    clear regIdx;

  end

  rows_to_rm = all(C.C == 0, 2);
  C.C(rows_to_rm, :) = [];

  % do not create this contrast if a condition is missing
  if exist('status', 'var')
    if ~status
      msg = sprintf('Skipping contrast %s: runs are missing condition %s', ...
                    thisContrast.Name, cdtName);
      id = 'runMissingCondition';
      logger('WARNING', msg, 'id', id, 'filename', mfilename());

    else
      [contrasts, count] = appendContrast(contrasts, C, count, thisContrast.Test);

    end
  end

end

function [contrasts, count] = crossRunContrast(model, node, thisContrast, contrasts, count)
  % Build a within-subject run contrast from Factor-derived ConditionList names.
  %
  % Each entry in thisContrast.ConditionList must match the pattern
  %   "run_{N}_contrast_{ContrastName}"
  % produced by Factor(["run","contrast"]).  The function looks up the run's
  % SPM.Sess columns, retrieves the parent contrast's condition weights, and
  % combines them: C(run_i) = parentWeight_j * subjectWeight_i for each regressor j.

  if ~strcmp(thisContrast.Test, 't')
    return
  end

  SPM = model.SPM;

  % Resolve parent (Run-level) node once
  sourceNode = model.get_source_node(node.Name);

  C = newContrast(SPM, thisContrast.Name, thisContrast.Test, thisContrast.ConditionList);
  allFound = true;

  for iSes = 1:length(thisContrast.ConditionList)

    factorName = thisContrast.ConditionList{iSes};

    % Parse  "run_{runNum}_contrast_{contrastName}"
    tok = regexp(factorName, '^run_(\d+)_contrast_(.+)$', 'tokens', 'once');
    if isempty(tok)
      msg = sprintf('Cannot parse run/contrast from ConditionList entry "%s"', factorName);
      logger('WARNING', msg, 'id', 'crossRunParseError', 'filename', mfilename());
      allFound = false;
      break
    end
    runLabel        = tok{1};   % e.g. '1'
    parentCtrName   = tok{2};   % e.g. 'Repeated_vs_Unrepeated'

    % Find the SPM session that corresponds to this run
    if isfield(SPM.Sess, 'run')
      iSPMSess = find(strcmp({SPM.Sess.run}, runLabel));
    else
      iSPMSess = str2double(runLabel);
    end

    if isempty(iSPMSess)
      msg = sprintf('No SPM session found for run-%s', runLabel);
      logger('WARNING', msg, 'id', 'crossRunMissingSess', 'filename', mfilename());
      allFound = false;
      break
    end

    runCols = SPM.Sess(iSPMSess).col;   % column indices belonging to this run

    % Find the named contrast in the source (Run-level) node
    parentCtr = [];
    if isfield(sourceNode, 'Contrasts')
      for iPar = 1:numel(sourceNode.Contrasts)
        ctr = sourceNode.Contrasts{iPar};
        if isfield(ctr, 'Name') && strcmp(ctr.Name, parentCtrName)
          parentCtr = ctr;
          break
        end
      end
    end

    if isempty(parentCtr)
      msg = sprintf('Parent contrast "%s" not found in source node', parentCtrName);
      logger('WARNING', msg, 'id', 'crossRunMissingParent', 'filename', mfilename());
      allFound = false;
      break
    end

    % Apply parent contrast weights restricted to this run's columns
    for iCdt = 1:numel(parentCtr.ConditionList)
      cdtName = parentCtr.ConditionList{iCdt};
      [~, allRegIdx] = getRegressorIdx(cdtName, SPM);
      allRegIdx = find(allRegIdx);
      runRegIdx = intersect(allRegIdx, runCols);

      if isempty(runRegIdx)
        msg = sprintf('No regressor for "%s" in run-%s', cdtName, runLabel);
        logger('WARNING', msg, 'id', 'crossRunMissingReg', 'filename', mfilename());
        allFound = false;
        break
      end

      C.C(end, runRegIdx) = parentCtr.Weights(iCdt) * thisContrast.Weights(iSes);
    end

    if ~allFound
      break
    end

  end

  if allFound && any(C.C(:) ~= 0)
    [contrasts, count] = appendContrast(contrasts, C, count, thisContrast.Test);
  end

end
