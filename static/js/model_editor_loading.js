(function(global) {
  function createModelLoadingHelpers(options = {}) {
    const setStatus = options.setStatus;
    const setModel = options.setModel;
    const setModelDraft = options.setModelDraft;
    const clearTransformerUnsavedChanges = options.clearTransformerUnsavedChanges;
    const refreshInputEntityOptions = options.refreshInputEntityOptions;
    const refreshModelEditorHintData = options.refreshModelEditorHintData;
    const renderModelStructure = options.renderModelStructure;
    const renderNodeList = options.renderNodeList;
    const resetSelectionToModel = options.resetSelectionToModel;
    const isFullEditor = options.isFullEditor;
    const renderAccordionEditor = options.renderAccordionEditor;
    const refreshRawEditorFromSelection = options.refreshRawEditorFromSelection;
    const applyPendingTransformerIntoCurrentModel = options.applyPendingTransformerIntoCurrentModel;
    const setPathLabel = options.setPathLabel;
    const clearUiOnLoadFailure = options.clearUiOnLoadFailure;

    async function fetchModel(path) {
      try {
        if (typeof setStatus === 'function') {
          setStatus('Loading model...', 'info');
        }
        const response = await fetch(`/file_content?path=${encodeURIComponent(path)}`);
        if (!response.ok) {
          throw new Error('Model file not found');
        }

        const modelText = await response.text();
        const parsedModel = JSON.parse(modelText);
        if (!Array.isArray(parsedModel.Nodes)) parsedModel.Nodes = [];
        if (!Array.isArray(parsedModel.Edges)) parsedModel.Edges = [];

        if (typeof setModel === 'function') {
          setModel(parsedModel);
        }
        if (typeof setModelDraft === 'function') {
          setModelDraft(parsedModel);
        }
        if (typeof clearTransformerUnsavedChanges === 'function') {
          clearTransformerUnsavedChanges();
        }
        if (typeof setPathLabel === 'function') {
          setPathLabel(path);
        }

        if (typeof refreshInputEntityOptions === 'function') {
          await refreshInputEntityOptions(false);
        }
        if (typeof refreshModelEditorHintData === 'function') {
          await refreshModelEditorHintData(parsedModel);
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

        if (typeof renderAccordionEditor === 'function' && typeof isFullEditor === 'function' && isFullEditor()) {
          renderAccordionEditor();
        }
        if (typeof refreshRawEditorFromSelection === 'function') {
          refreshRawEditorFromSelection();
        }

        const appliedPendingPayload = typeof applyPendingTransformerIntoCurrentModel === 'function'
          ? await applyPendingTransformerIntoCurrentModel(path)
          : false;
        if (!appliedPendingPayload && typeof setStatus === 'function') {
          setStatus('Model loaded.', 'success');
        }
      } catch (error) {
        if (typeof setModel === 'function') {
          setModel(null);
        }
        if (typeof clearUiOnLoadFailure === 'function') {
          clearUiOnLoadFailure();
        }
        if (typeof setStatus === 'function') {
          setStatus(`Load failed: ${error.message}`, 'danger');
        }
      }
    }

    return {
      fetchModel,
    };
  }

  global.BidspmModelEditorLoading = {
    createModelLoadingHelpers,
  };
})(window);