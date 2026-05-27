(function(global) {
  function registerTransformerAppliedListener(options = {}) {
    const transformerAppliedEvent = String(options.transformerAppliedEvent || 'bidspm-transformer-applied');
    const applyTransformerPayloadIntoCurrentModel = options.applyTransformerPayloadIntoCurrentModel;
    const applyPendingTransformerIntoCurrentModel = options.applyPendingTransformerIntoCurrentModel;
    const normalizeStringArray = options.normalizeStringArray;
    const setStatus = options.setStatus;

    global.addEventListener('message', async (event) => {
      if (event.origin !== global.location.origin) return;
      const data = event.data && typeof event.data === 'object' ? event.data : null;
      if (!data || data.type !== transformerAppliedEvent) return;

      const hasDirectPayload = Boolean(
        data.transformations
        && typeof data.transformations === 'object'
        && !Array.isArray(data.transformations)
        && Array.isArray(data.transformations.Instructions)
      );
      if (hasDirectPayload) {
        const directPayload = {
          launchId: String(data.launchId || '').trim(),
          projectId: String(data.projectId || '').trim(),
          modelPath: String(data.modelPath || '').trim(),
          transformations: structuredClone(data.transformations),
          generatedColumns: typeof normalizeStringArray === 'function' ? normalizeStringArray(data.generatedColumns) : [],
          targetLevels: typeof normalizeStringArray === 'function' ? normalizeStringArray(data.targetLevels) : [],
          sourceScope: String(data.sourceScope || '').trim()
        };
        const appliedDirect = typeof applyTransformerPayloadIntoCurrentModel === 'function'
          ? await applyTransformerPayloadIntoCurrentModel(
              directPayload,
              String(data.modelPath || '').trim(),
              { clearPending: true }
            )
          : false;
        if (!appliedDirect && typeof setStatus === 'function') {
          setStatus('Transformer payload received but could not be applied to the currently loaded model.', 'warning');
        }
        return;
      }

      const applied = typeof applyPendingTransformerIntoCurrentModel === 'function'
        ? await applyPendingTransformerIntoCurrentModel(String(data.modelPath || '').trim())
        : false;
      if (!applied && typeof setStatus === 'function') {
        setStatus('Transformer payload received but could not be applied to the currently loaded model.', 'warning');
      }
    });
  }

  global.BidspmModelEditorTransformerEvents = {
    registerTransformerAppliedListener,
  };
})(window);