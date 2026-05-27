(function(global) {
  function createTransformerApplyHelpers(options = {}) {
    const consumeTransformerPayload = options.consumeTransformerPayload;
    const readPendingTransformerPayload = options.readPendingTransformerPayload;
    const clearPendingTransformerPayload = options.clearPendingTransformerPayload;
    const clearTransformerLaunchContext = options.clearTransformerLaunchContext;
    const markTransformerUnsavedChanges = options.markTransformerUnsavedChanges;
    const getCurrentModelPathValue = options.getCurrentModelPathValue;
    const getModel = options.getModel;
    const setModelDraft = options.setModelDraft;
    const refreshModelEditorHintData = options.refreshModelEditorHintData;
    const renderModelStructure = options.renderModelStructure;
    const renderNodeList = options.renderNodeList;
    const resetSelectionToModel = options.resetSelectionToModel;
    const renderAccordionEditor = options.renderAccordionEditor;
    const refreshRawEditorFromSelection = options.refreshRawEditorFromSelection;
    const setStatus = options.setStatus;

    async function applyTransformerPayloadIntoCurrentModel(payload, modelPathHint = '', applyOptions = {}) {
      const clearPending = Boolean(applyOptions.clearPending);
      const targetPath = String(
        modelPathHint || (typeof getCurrentModelPathValue === 'function' ? getCurrentModelPathValue() : '')
      ).trim();
      const model = typeof getModel === 'function' ? getModel() : null;
      if (!targetPath || !model || typeof model !== 'object') return false;

      const result = typeof consumeTransformerPayload === 'function'
        ? consumeTransformerPayload(payload, targetPath)
        : null;
      if (!result) return false;
      if (result.staleHandoff) {
        if (clearPending && typeof clearPendingTransformerPayload === 'function') {
          clearPendingTransformerPayload();
        }
        if (typeof setStatus === 'function') {
          setStatus(result.message, result.tone || 'warning');
        }
        return true;
      }

      if (typeof setModelDraft === 'function') {
        setModelDraft(typeof getModel === 'function' ? getModel() : model);
      }
      if (typeof refreshModelEditorHintData === 'function') {
        await refreshModelEditorHintData(typeof getModel === 'function' ? getModel() : model);
      }
      if (typeof renderModelStructure === 'function') {
        renderModelStructure();
      }
      if (typeof renderNodeList === 'function') {
        renderNodeList();
      }
      if (typeof resetSelectionToModel === 'function') {
        resetSelectionToModel();
      }
      if (typeof renderAccordionEditor === 'function') {
        renderAccordionEditor();
      }
      if (typeof refreshRawEditorFromSelection === 'function') {
        refreshRawEditorFromSelection();
      }
      if (result.appliedToTargetNodes) {
        if (typeof markTransformerUnsavedChanges === 'function') {
          markTransformerUnsavedChanges(result.message);
        }
        if (clearPending) {
          if (typeof clearPendingTransformerPayload === 'function') {
            clearPendingTransformerPayload();
          }
          if (String(payload?.launchId || '').trim() && typeof clearTransformerLaunchContext === 'function') {
            clearTransformerLaunchContext();
          }
        }
      }
      if (typeof setStatus === 'function') {
        setStatus(result.message, result.tone || 'success');
      }
      return true;
    }

    async function applyPendingTransformerIntoCurrentModel(modelPathHint = '') {
      const payload = typeof readPendingTransformerPayload === 'function'
        ? readPendingTransformerPayload()
        : null;
      if (!payload) return false;
      return applyTransformerPayloadIntoCurrentModel(payload, modelPathHint, { clearPending: true });
    }

    return {
      applyTransformerPayloadIntoCurrentModel,
      applyPendingTransformerIntoCurrentModel,
    };
  }

  global.BidspmModelEditorTransformerApply = {
    createTransformerApplyHelpers,
  };
})(window);