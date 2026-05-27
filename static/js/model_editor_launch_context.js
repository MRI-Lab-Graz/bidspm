(function(global) {
  function createLaunchContextHelpers(options = {}) {
    const transformerLaunchContextKey = String(
      options.transformerLaunchContextKey || 'bidspm.transformerLaunchContext'
    );
    const currentProjectId = String(options.currentProjectId || '').trim();
    const createTransformerLaunchId = options.createTransformerLaunchId;
    const normalizeLaunchStringArray = options.normalizeLaunchStringArray;
    const getModel = options.getModel;
    const getModelDraft = options.getModelDraft;
    const getModelPathFallback = options.getModelPathFallback;
    const getCurrentNodeIndex = options.getCurrentNodeIndex;
    const getCurrentSelection = options.getCurrentSelection;

    function getCurrentModelPathValue() {
      const input = document.getElementById('model-path-input');
      const fallback = typeof getModelPathFallback === 'function' ? getModelPathFallback() : '';
      return String(input?.value || fallback || '').trim();
    }

    function getTransformerBuilderUrl() {
      return currentProjectId
        ? `/transformer-builder/${encodeURIComponent(currentProjectId)}`
        : '/transformer-builder';
    }

    function resolveTransformerLaunchNodeIndex(nodeIndex = null) {
      if (Number.isInteger(nodeIndex)) return nodeIndex;
      if (Number.isInteger(global.modelEditorInlineTransformerNodeIdx)) return global.modelEditorInlineTransformerNodeIdx;
      const currentNodeIdx = typeof getCurrentNodeIndex === 'function' ? getCurrentNodeIndex() : null;
      if (Number.isInteger(currentNodeIdx)) return currentNodeIdx;
      const selection = typeof getCurrentSelection === 'function' ? getCurrentSelection() : null;
      if (selection && selection.type === 'nodeField' && Number.isInteger(selection.idx)) {
        return selection.idx;
      }
      return null;
    }

    function persistTransformerLaunchContextPayload(payload) {
      const value = (payload && typeof payload === 'object' && !Array.isArray(payload))
        ? payload
        : {};
      try {
        sessionStorage.setItem(transformerLaunchContextKey, JSON.stringify(value));
        return true;
      } catch (withSnapshotError) {
        const fallback = { ...value };
        delete fallback.modelSnapshot;
        try {
          sessionStorage.setItem(transformerLaunchContextKey, JSON.stringify(fallback));
          return true;
        } catch (fallbackError) {
          try {
            sessionStorage.removeItem(transformerLaunchContextKey);
          } catch (cleanupError) {
            // Ignore storage cleanup failures.
          }
          return false;
        }
      }
    }

    function prepareTransformerLaunchContext(nodeIndex = null) {
      const resolvedNodeIndex = resolveTransformerLaunchNodeIndex(nodeIndex);
      const model = typeof getModel === 'function' ? getModel() : null;
      const launchNode = (Number.isInteger(resolvedNodeIndex) && Array.isArray(model?.Nodes))
        ? model.Nodes[resolvedNodeIndex]
        : null;
      const launchNodeLevel = String(launchNode?.Level || '').trim();
      const modelDraft = typeof getModelDraft === 'function' ? getModelDraft() : null;
      const selectedTasks = typeof normalizeLaunchStringArray === 'function'
        ? normalizeLaunchStringArray(modelDraft?.Input?.task)
        : [];
      const launchSnapshotSource = (modelDraft && typeof modelDraft === 'object' && !Array.isArray(modelDraft))
        ? modelDraft
        : model;
      const payload = {
        launchId: typeof createTransformerLaunchId === 'function'
          ? createTransformerLaunchId()
          : `transformer-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
        projectId: currentProjectId,
        modelPath: getCurrentModelPathValue(),
        bidsDir: String(document.getElementById('input-BIDS_DIR')?.value || '').trim(),
        modelSnapshot: (launchSnapshotSource && typeof launchSnapshotSource === 'object' && !Array.isArray(launchSnapshotSource))
          ? structuredClone(launchSnapshotSource)
          : null,
        launchAt: Date.now(),
        nodeIndex: Number.isInteger(resolvedNodeIndex) ? resolvedNodeIndex : null,
        inputTasks: selectedTasks,
        taskFilter: selectedTasks.length === 1 ? selectedTasks[0] : '',
        nodeLevel: launchNodeLevel || null,
        sourceScope: launchNodeLevel
          ? (launchNodeLevel.toLowerCase() === 'run' ? 'events' : 'participants')
          : 'auto'
      };
      persistTransformerLaunchContextPayload(payload);
    }

    return {
      getCurrentModelPathValue,
      getTransformerBuilderUrl,
      resolveTransformerLaunchNodeIndex,
      persistTransformerLaunchContextPayload,
      prepareTransformerLaunchContext,
    };
  }

  global.BidspmModelEditorLaunchContext = {
    createLaunchContextHelpers,
  };
})(window);