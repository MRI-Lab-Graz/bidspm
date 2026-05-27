(function () {
  'use strict';

  function createTransformerBuilderModelSelection(config) {
    const pathUtils = window.BIDSPMTransformerBuilderPathUtils;
    if (!pathUtils) {
      throw new Error('Transformer Builder path utilities are required before model selection helpers.');
    }

    const {
      projectModelsFile,
      launchContext,
      nodeLevelOptions,
      maybeBootstrapPipelineFromModel,
      setStatus,
      escHtml,
      escAttr,
      normalizeNodeLevel,
      getTargetLevels,
      getTransformerPayload,
      getGeneratedColumns,
    } = config || {};

    if (typeof maybeBootstrapPipelineFromModel !== 'function' ||
        typeof setStatus !== 'function' ||
        typeof escHtml !== 'function' ||
        typeof escAttr !== 'function' ||
        typeof normalizeNodeLevel !== 'function' ||
        typeof getTargetLevels !== 'function' ||
        typeof getTransformerPayload !== 'function' ||
        typeof getGeneratedColumns !== 'function') {
      throw new Error('Transformer Builder model selection dependencies are incomplete.');
    }

    const {
      normalizeFsPath,
      areModelPathsEquivalent,
      getParentPath,
      getFileName,
      normalizeStringArray,
    } = pathUtils;

    const modelFileCache = new Map();
    let liveValidationTimer = null;
    let liveValidationRunId = 0;

    function getSelectedModelPath() {
      const select = document.getElementById('select-target-model');
      return normalizeFsPath(select?.value || '');
    }

    function setLiveValidationState(kind, message, details = [], modelPath = '') {
      const badge = document.getElementById('live-validation-badge');
      const messageEl = document.getElementById('live-validation-message');
      const detailsEl = document.getElementById('live-validation-details');
      const pathEl = document.getElementById('live-validation-model-path');

      const badgeMap = {
        idle: 'bg-secondary',
        checking: 'bg-info',
        success: 'bg-success',
        warning: 'bg-warning text-dark',
        danger: 'bg-danger',
      };

      badge.className = `badge ${badgeMap[kind] || 'bg-secondary'}`;
      badge.textContent = kind;
      messageEl.textContent = message;
      detailsEl.innerHTML = (details || []).map(item => `<li>${escHtml(item)}</li>`).join('');
      pathEl.textContent = modelPath ? `model: ${modelPath}` : '';
    }

    async function browseJsonFiles(path) {
      const normalizedPath = normalizeFsPath(path);
      if (!normalizedPath) return [];

      const response = await fetch(`/browse?path=${encodeURIComponent(normalizedPath)}&extensions=.json`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `Browse failed for ${normalizedPath}`);
      if (data.error) throw new Error(data.error);

      return (data.items || [])
        .filter(item => item.type === 'file' && String(item.name || '').toLowerCase().endsWith('.json'))
        .map(item => normalizeFsPath(item.path))
        .filter(Boolean);
    }

    function setTargetModelOptions(paths, preferredPath = '') {
      const select = document.getElementById('select-target-model');
      const normalizedPreferred = normalizeFsPath(preferredPath);
      const deduped = Array.from(new Set((paths || []).map(normalizeFsPath).filter(Boolean)));
      if (normalizedPreferred && !deduped.includes(normalizedPreferred)) {
        deduped.unshift(normalizedPreferred);
      }

      deduped.sort((left, right) => {
        const byName = getFileName(left).localeCompare(getFileName(right));
        return byName !== 0 ? byName : left.localeCompare(right);
      });

      if (!deduped.length) {
        select.innerHTML = '<option value="">— no model file found —</option>';
        return;
      }

      select.innerHTML = deduped.map(path => {
        const fileName = escHtml(getFileName(path));
        const fullPath = escHtml(path);
        return `<option value="${escAttr(path)}">${fileName} — ${fullPath}</option>`;
      }).join('');

      const selectedPath = normalizeFsPath(select.value);
      const preferredSelected = normalizedPreferred
        ? deduped.find(path => areModelPathsEquivalent(path, normalizedPreferred)) || ''
        : '';
      const nextSelected = preferredSelected
        || (selectedPath && deduped.includes(selectedPath) ? selectedPath : '')
        || deduped[0];
      select.value = nextSelected;
    }

    async function refreshModelCandidates() {
      const refreshBtn = document.getElementById('btn-refresh-models');
      refreshBtn.disabled = true;
      refreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Loading';

      try {
        const currentSelected = getSelectedModelPath();
        const contextModel = normalizeFsPath(launchContext?.modelPath || '');
        const projectModel = normalizeFsPath(projectModelsFile || '');
        const seededPaths = [currentSelected, contextModel, projectModel].filter(Boolean);

        const dirs = new Set();
        seededPaths.forEach(path => {
          const parent = getParentPath(path);
          if (parent) dirs.add(parent);
        });

        const foundPaths = new Set(seededPaths);
        for (const dir of dirs) {
          const files = await browseJsonFiles(dir);
          files.forEach(path => foundPaths.add(path));
        }

        const preferredPath = currentSelected || contextModel || projectModel || '';
        setTargetModelOptions(Array.from(foundPaths), preferredPath);
      } catch (error) {
        setStatus(`Could not refresh model candidates: ${error.message}`, 'warning');
        setTargetModelOptions([], getSelectedModelPath());
      } finally {
        refreshBtn.disabled = false;
        refreshBtn.innerHTML = '<i class="fas fa-sync-alt me-1"></i>Refresh Models';
      }
    }

    async function loadModelForValidation(modelPath) {
      const normalizedPath = normalizeFsPath(modelPath);
      if (!normalizedPath) throw new Error('No model path selected');

      if (!modelFileCache.has(normalizedPath)) {
        const response = await fetch(`/file_content?path=${encodeURIComponent(normalizedPath)}`);
        if (!response.ok) throw new Error('Selected model file could not be loaded');
        const text = await response.text();
        modelFileCache.set(normalizedPath, JSON.parse(text));
      }

      return structuredClone(modelFileCache.get(normalizedPath));
    }

    function buildLiveModelPreview(baseModel) {
      const model = structuredClone(baseModel || {});
      const transformations = getTransformerPayload();
      const generatedColumns = normalizeStringArray(getGeneratedColumns().map(column => column.name));
      const targetLevels = getTargetLevels();
      const targetNodes = Array.isArray(model.Nodes)
        ? model.Nodes.filter(node => {
            if (!node || typeof node !== 'object') return false;
            const level = normalizeNodeLevel(node.Level);
            return targetLevels.includes(level);
          })
        : [];

      if (!targetNodes.length) {
        const targetText = targetLevels.length === nodeLevelOptions.length
          ? 'selected'
          : targetLevels.join('/');
        return {
          model,
          targetNodeCount: 0,
          targetLevels,
          generatedColumns,
          warning: `Model has no ${targetText} node(s). Transformer output has nowhere to attach.`,
        };
      }

      const instructions = Array.isArray(transformations.Instructions)
        ? structuredClone(transformations.Instructions)
        : [];

      targetNodes.forEach(node => {
        const existingTransformations = (node.Transformations && typeof node.Transformations === 'object' && !Array.isArray(node.Transformations))
          ? node.Transformations
          : {};
        const nextTransformations = {
          ...existingTransformations,
          Transformer: transformations.Transformer || 'bidspm',
          Instructions: instructions,
        };
        delete nextTransformations.GeneratedColumns;
        node.Transformations = nextTransformations;
      });

      return {
        model,
        targetNodeCount: targetNodes.length,
        targetLevels,
        generatedColumns,
        warning: '',
      };
    }

    async function runLiveModelValidation() {
      const runId = ++liveValidationRunId;
      const modelPath = getSelectedModelPath();
      if (!modelPath) {
        setLiveValidationState('idle', 'Select a target model to validate transformer output on the fly.');
        return;
      }

      setLiveValidationState('checking', 'Validating transformed model preview…', [], modelPath);

      try {
        const baseModel = await loadModelForValidation(modelPath);
        if (runId !== liveValidationRunId) return;

        const preview = buildLiveModelPreview(baseModel);
        const response = await fetch('/validate_model', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: preview.model }),
        });
        const result = await response.json();
        if (runId !== liveValidationRunId) return;

        const details = [];
        details.push(`Target levels: ${preview.targetLevels.join(', ')}`);
        details.push(`Nodes affected: ${preview.targetNodeCount}`);
        details.push(`Generated columns: ${preview.generatedColumns.length}`);
        if (preview.warning) details.push(preview.warning);

        if (result.valid) {
          if (result.warning) details.push(result.warning);
          setLiveValidationState('success', 'Schema validation passed for the live transformed model preview.', details, modelPath);
        } else {
          if (result.error) details.push(result.error);
          setLiveValidationState('danger', 'Schema validation failed for the live transformed model preview.', details, modelPath);
        }
      } catch (error) {
        if (runId !== liveValidationRunId) return;
        setLiveValidationState('danger', `Could not validate preview: ${error.message}`, [], modelPath);
      }
    }

    function scheduleLiveModelValidation() {
      if (liveValidationTimer) {
        clearTimeout(liveValidationTimer);
      }
      liveValidationTimer = setTimeout(() => {
        runLiveModelValidation();
      }, 250);
    }

    function clearModelFileCache() {
      modelFileCache.clear();
    }

    async function initializeModelSelection() {
      await refreshModelCandidates();
      await maybeBootstrapPipelineFromModel();
      scheduleLiveModelValidation();
    }

    return Object.freeze({
      clearModelFileCache,
      getSelectedModelPath,
      initializeModelSelection,
      refreshModelCandidates,
      scheduleLiveModelValidation,
    });
  }

  window.BIDSPMTransformerBuilderModelSelection = createTransformerBuilderModelSelection;
})();