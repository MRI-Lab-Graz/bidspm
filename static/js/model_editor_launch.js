(function(global) {
  function createLaunchHelpers(options = {}) {
    const transformerLaunchContextKey = String(
      options.transformerLaunchContextKey || 'bidspm.transformerLaunchContext'
    );
    const pendingTransformerKey = String(
      options.pendingTransformerKey || 'bidspm.pendingTransformerModel'
    );

    // Path helpers are shared with the transformer builder (transformer_builder_path_utils.js).
    const {
      normalizeFsPath,
      stripPathQueryAndHash,
      safeDecodePath,
      areModelPathsEquivalent,
    } = global.BIDSPMTransformerBuilderPathUtils;

    function normalizeLaunchStringArray(value) {
      if (Array.isArray(value)) {
        return value.map(item => String(item || '').trim()).filter(Boolean);
      }
      if (value === undefined || value === null || typeof value === 'object') return [];
      const normalized = String(value || '').trim();
      return normalized ? [normalized] : [];
    }

    function readTransformerLaunchContext() {
      try {
        const raw = sessionStorage.getItem(transformerLaunchContextKey);
        if (!raw) return null;
        return JSON.parse(raw);
      } catch (error) {
        return null;
      }
    }

    function clearTransformerLaunchContext() {
      try {
        sessionStorage.removeItem(transformerLaunchContextKey);
      } catch (error) {
        // Ignore storage cleanup failures.
      }
    }

    function createTransformerLaunchId() {
      return `transformer-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    }

    function readPendingTransformerPayload() {
      try {
        const raw = sessionStorage.getItem(pendingTransformerKey);
        if (!raw) return null;
        return JSON.parse(raw);
      } catch (error) {
        return null;
      }
    }

    function clearPendingTransformerPayload() {
      try {
        sessionStorage.removeItem(pendingTransformerKey);
      } catch (error) {
        // Ignore storage cleanup failures.
      }
    }

    return {
      normalizeLaunchStringArray,
      readTransformerLaunchContext,
      clearTransformerLaunchContext,
      createTransformerLaunchId,
      normalizeFsPath,
      stripPathQueryAndHash,
      safeDecodePath,
      areModelPathsEquivalent,
      readPendingTransformerPayload,
      clearPendingTransformerPayload,
    };
  }

  global.BidspmModelEditorLaunch = {
    createLaunchHelpers,
  };
})(window);