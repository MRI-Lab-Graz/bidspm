(function(global) {
  function createTransformerPayloadHelpers(options = {}) {
    const currentProjectId = String(options.currentProjectId || '').trim();
    const getModel = options.getModel;
    const setModel = options.setModel;
    const areModelPathsEquivalent = options.areModelPathsEquivalent;
    const readTransformerLaunchContext = options.readTransformerLaunchContext;
    const readPendingTransformerPayload = options.readPendingTransformerPayload;
    const normalizeStringArray = options.normalizeStringArray;
    const extendInterestRegressorPool = options.extendInterestRegressorPool;

    function consumeTransformerPayload(payload, targetModelPath) {
      const model = typeof getModel === 'function' ? getModel() : null;
      if (!payload || !model || typeof model !== 'object') return null;

      const payloadProjectId = String(payload.projectId || '').trim();
      if (payloadProjectId && currentProjectId && payloadProjectId !== currentProjectId) {
        return null;
      }

      const payloadModelPath = String(payload.modelPath || '').trim();
      const normalizedTargetPath = String(targetModelPath || '').trim();
      if (
        payloadModelPath
        && normalizedTargetPath
        && typeof areModelPathsEquivalent === 'function'
        && !areModelPathsEquivalent(payloadModelPath, normalizedTargetPath)
      ) {
        return null;
      }

      let activeModel = model;
      const payloadLaunchId = String(payload.launchId || '').trim();
      if (payloadLaunchId) {
        const launchContext = typeof readTransformerLaunchContext === 'function'
          ? readTransformerLaunchContext()
          : null;
        const launchContextId = String(launchContext?.launchId || '').trim();
        const launchContextPath = String(launchContext?.modelPath || '').trim();
        const snapshotTargetPath = payloadModelPath || normalizedTargetPath || launchContextPath;
        const payloadModelSnapshot = (launchContext?.modelSnapshot && typeof launchContext.modelSnapshot === 'object' && !Array.isArray(launchContext.modelSnapshot))
          ? structuredClone(launchContext.modelSnapshot)
          : null;
        const validLaunchSnapshot = Boolean(
          launchContextId
          && launchContextId === payloadLaunchId
          && payloadModelSnapshot
          && Array.isArray(payloadModelSnapshot.Nodes)
          && (
            !launchContextPath
            || !snapshotTargetPath
            || typeof areModelPathsEquivalent !== 'function'
            || areModelPathsEquivalent(launchContextPath, snapshotTargetPath)
          )
        );

        if (!validLaunchSnapshot) {
          return {
            appliedToTargetNodes: false,
            staleHandoff: true,
            tone: 'warning',
            message: 'Transformer output was returned from a stale editor session, so it was not applied. Reopen Transformer Builder from the current model editor and apply again.'
          };
        }

        // The snapshot is only used to confirm this Apply event matches the launch
        // that opened Transformer Builder — it must NOT replace the live model.
        // Doing so previously discarded any edits made in the model editor while
        // the builder was open (e.g. enabling DummyContrasts), since the snapshot
        // reflects the model as it was at launch time, not now.
        activeModel = model;
      }

      const generatedColumns = typeof normalizeStringArray === 'function'
        ? normalizeStringArray(payload.generatedColumns)
        : [];
      const instructions = Array.isArray(payload.transformations?.Instructions)
        ? structuredClone(payload.transformations.Instructions)
        : [];
      const allowedLevels = ['Run'];
      const normalizeLevel = (value) => {
        const raw = String(value || '').trim().toLowerCase();
        return allowedLevels.find(level => level.toLowerCase() === raw) || '';
      };
      const targetLevels = (typeof normalizeStringArray === 'function'
        ? normalizeStringArray(payload.targetLevels)
        : [])
        .map(normalizeLevel)
        .filter(level => allowedLevels.includes(level));
      const effectiveTargetLevels = targetLevels.length ? Array.from(new Set(targetLevels)) : ['Run'];
      const targetNodes = Array.isArray(activeModel.Nodes)
        ? activeModel.Nodes.filter(
            node => node && typeof node === 'object' && effectiveTargetLevels.includes(normalizeLevel(node.Level))
          )
        : [];

      if (!targetNodes.length) {
        const targetText = effectiveTargetLevels.length === allowedLevels.length
          ? 'selected'
          : effectiveTargetLevels.join('/');
        return {
          appliedToTargetNodes: false,
          targetLevels: effectiveTargetLevels,
          tone: 'warning',
          message: `Pending transformer output found, but the model has no ${targetText} node(s) to apply it to.`
        };
      }

      targetNodes.forEach(node => {
        const existingTransformations = (node.Transformations && typeof node.Transformations === 'object' && !Array.isArray(node.Transformations))
          ? node.Transformations
          : {};
        const nextTransformations = {
          ...existingTransformations,
          Transformer: payload.transformations?.Transformer || 'bidspm',
          Instructions: instructions
        };
        if (generatedColumns.length) {
          nextTransformations.GeneratedColumns = generatedColumns;
        } else {
          delete nextTransformations.GeneratedColumns;
        }
        node.Transformations = nextTransformations;
      });

      if (typeof extendInterestRegressorPool === 'function') {
        extendInterestRegressorPool(generatedColumns);
      }

      const levelsText = effectiveTargetLevels.join(', ');
      return {
        appliedToTargetNodes: true,
        targetLevels: effectiveTargetLevels,
        tone: 'success',
        message: `Applied transformer pipeline to ${targetNodes.length} node(s) at level(s): ${levelsText}. Generated variables: ${generatedColumns.length}. Design Matrix was not changed; add generated variables to Model.X manually if needed. Save Model to persist it.`
      };
    }

    function consumePendingTransformerPayload(targetModelPath) {
      const payload = typeof readPendingTransformerPayload === 'function'
        ? readPendingTransformerPayload()
        : null;
      return consumeTransformerPayload(payload, targetModelPath);
    }

    return {
      consumeTransformerPayload,
      consumePendingTransformerPayload,
    };
  }

  global.BidspmModelEditorTransformerPayload = {
    createTransformerPayloadHelpers,
  };
})(window);