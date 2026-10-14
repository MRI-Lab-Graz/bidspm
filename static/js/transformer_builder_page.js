// transformer_builder_page.js
// Extracted from templates/transformer_builder.html: the page controller (state, event wiring, apply-to-model,
// launch-context handling) built on the transformer_builder_* factories.
// Needs window.BIDSPM_TRANSFORMER_CONTEXT = {projectId, modelsFile}, set by a small inline script in the template.

(function () {
  'use strict';

  const CURRENT_PROJECT_ID = window.BIDSPM_TRANSFORMER_CONTEXT.projectId;
  const PROJECT_MODELS_FILE = window.BIDSPM_TRANSFORMER_CONTEXT.modelsFile;
  const TRANSFORMER_LAUNCH_CONTEXT_KEY = 'bidspm.transformerLaunchContext';
  const PENDING_TRANSFORMER_KEY = 'bidspm.pendingTransformerModel';
  const TRANSFORMER_APPLIED_EVENT = 'bidspm-transformer-applied';
  const EMBEDDED_MODE = window.self !== window.top;
  // bidspm only ever executes node Transformations for Run-level events.tsv data
  // (see convertOnsetTsvToMat.m) — Session/Subject/Dataset nodes never run them,
  // so they aren't offered as targets here.
  const NODE_LEVEL_OPTIONS = ['Run'];
  const transformerPathUtils = window.BIDSPMTransformerBuilderPathUtils;
  const modelSelectionFactory = window.BIDSPMTransformerBuilderModelSelection;
  const browserFactory = window.BIDSPMTransformerBuilderBrowser;
  const scanPreviewFactory = window.BIDSPMTransformerBuilderScanPreview;
  const columnsFactory = window.BIDSPMTransformerBuilderColumns;
  const pipelineFactory = window.BIDSPMTransformerBuilderPipeline;
  const REQUIRED_OUTPUT_OPS = new Set([
    'Assign',
    'Filter',
    'Concatenate',
    'Replace',
    'DropNA',
    'Split',
    'LabelIdenticalRows',
    'Scale',
    'Mean',
    'Std',
    'Threshold'
  ]);
  const MUNGE_OPERATION_NAMES = new Set([
    'Assign', 'Filter', 'Concatenate', 'Factor', 'Replace', 'Copy', 'DropNA',
    'Split', 'LabelIdenticalRows', 'MergeIdenticalRows', 'Select', 'Delete'
  ]);
  const COMPUTE_OPERATION_NAMES = new Set([
    'Constant', 'Product', 'Scale', 'Mean', 'Std', 'Sum', 'Threshold'
  ]);

  if (!transformerPathUtils) {
    throw new Error('Transformer Builder path utilities failed to load.');
  }
  if (!modelSelectionFactory) {
    throw new Error('Transformer Builder model selection helpers failed to load.');
  }
  if (!browserFactory) {
    throw new Error('Transformer Builder browser helpers failed to load.');
  }
  if (!scanPreviewFactory) {
    throw new Error('Transformer Builder scan/preview helpers failed to load.');
  }
  if (!columnsFactory) {
    throw new Error('Transformer Builder columns helpers failed to load.');
  }
  if (!pipelineFactory) {
    throw new Error('Transformer Builder pipeline helpers failed to load.');
  }

  const {
    normalizeFsPath,
    areModelPathsEquivalent,
    getParentPath,
    getFileName,
    normalizeStringArray,
  } = transformerPathUtils;

  // ---- State ----
  let availableColumns = [];
  let columnValues = {};   // { col: [val1, val2, ...] }
  let pipelineColumnValues = {}; // raw + derived/generated column value domains
  let lastScanData = null; // full API response for resample
  let currentPreviewFile = null;
  const launchContext = readTransformerLaunchContext();
  let modelSelectionController;
  let pipelineController;
  const columnsController = columnsFactory({
    getAvailableColumns: () => availableColumns,
    getColumnValues: () => columnValues,
    getPipelineColumnValues: () => pipelineColumnValues,
    setPipelineColumnValues: value => {
      pipelineColumnValues = value;
    },
    extractOpsFromCard: card => pipelineController.extractOpsFromCard(card),
    escHtml,
    escAttr,
  });
  pipelineController = pipelineFactory({
    getSelectableColumns: () => columnsController.getSelectableColumns(),
    getColumnDomain: name => columnsController.getColumnDomain(name),
    normalizeColumnList: value => columnsController.normalizeColumnList(value),
    renderColumnsPool: () => columnsController.renderColumnsPool(),
    refreshPipelineColumnValues: () => columnsController.refreshPipelineColumnValues(),
    scheduleLiveModelValidation,
    setStatus,
    escHtml,
    escAttr,
    getTargetLevels,
    normalizeNodeLevel,
    getOperationCategory,
    loadModelForValidation: (...args) => modelSelectionController.loadModelForValidation(...args),
    getSelectedModelPath: () => modelSelectionController.getSelectedModelPath(),
    requiredOutputOps: REQUIRED_OUTPUT_OPS,
    setSeedColumns: columns => columnsController.setSeedColumns(columns),
  });
  modelSelectionController = modelSelectionFactory({
    projectModelsFile: PROJECT_MODELS_FILE,
    launchContext,
    nodeLevelOptions: NODE_LEVEL_OPTIONS,
    maybeBootstrapPipelineFromModel: force => pipelineController.maybeBootstrapPipelineFromModel(force, launchContext),
    setStatus,
    escHtml,
    escAttr,
    normalizeNodeLevel,
    getTargetLevels,
    getTransformerPayload: () => pipelineController.getTransformerPayload(),
    getGeneratedColumns: () => columnsController.getGeneratedColumns(),
  });
  const browserController = browserFactory({
    setStatus,
    scanEvents,
    escHtml,
    clearCurrentPreviewFile: () => {
      currentPreviewFile = null;
    },
  });
  const scanPreviewController = scanPreviewFactory({
    getAvailableColumns: () => availableColumns,
    setAvailableColumns: value => {
      availableColumns = value;
    },
    getColumnValues: () => columnValues,
    setColumnValues: value => {
      columnValues = value;
    },
    getCurrentPreviewFile: () => currentPreviewFile,
    setCurrentPreviewFile: value => {
      currentPreviewFile = value;
    },
    setLastScanData: value => {
      lastScanData = value;
    },
    getEffectiveSourceScope,
    updateScopeHint,
    getRequestedTaskFilter,
    mergeColumnValueMaps,
    normalizeStringArray,
    setStatus,
    escHtml,
    renderColumnsPool: () => columnsController.renderColumnsPool(),
    refreshPipelineColumnValues: () => columnsController.refreshPipelineColumnValues(),
    scheduleLiveModelValidation,
    launchContext,
    getTargetLevels,
    loadModelForValidation: (...args) => modelSelectionController.loadModelForValidation(...args),
    getSelectedModelPath: () => modelSelectionController.getSelectedModelPath(),
  });

  if (!document.getElementById('input-bids-dir').value.trim() && launchContext?.bidsDir) {
    document.getElementById('input-bids-dir').value = launchContext.bidsDir;
  }
  const launchNodeLevel = normalizeNodeLevel(launchContext?.nodeLevel);
  if (launchNodeLevel) {
    document.getElementById('select-target-level').value = launchNodeLevel;
  }
  const launchSourceScope = String(launchContext?.sourceScope || '').trim().toLowerCase();
  if (['auto', 'events', 'participants', 'combined'].includes(launchSourceScope)) {
    document.getElementById('select-source-scope').value = launchSourceScope;
  }
  const launchTaskFilter = normalizeLaunchTaskFilter(launchContext);
  let pendingLaunchTaskFilter = launchTaskFilter;
  updateScopeHint();
  updateLaunchContextHint();

  // ---- Bind top-bar controls ----
  document.getElementById('btn-scan-events').addEventListener('click', () => scanEvents(false));
  document.getElementById('btn-browse-bids').addEventListener('click', openBidsBrowser);
  document.getElementById('btn-browse-events').addEventListener('click', openEventsBrowser);
  document.getElementById('btn-apply-model').addEventListener('click', applyToModel);
  document.getElementById('btn-refresh-models').addEventListener('click', async () => {
    modelSelectionController.clearModelFileCache();
    await refreshModelCandidates();
    scheduleLiveModelValidation();
  });
  document.getElementById('select-target-model').addEventListener('change', () => {
    scheduleLiveModelValidation();
  });
  document.getElementById('select-target-level').addEventListener('change', () => {
    updateScopeHint();
    updateLaunchContextHint();
    currentPreviewFile = null;
    scanEvents(false);
    scheduleLiveModelValidation();
  });
  document.getElementById('select-source-scope').addEventListener('change', () => {
    updateScopeHint();
    currentPreviewFile = null;
    scanEvents(false);
    scheduleLiveModelValidation();
  });
  document.getElementById('btn-clear-events-file').addEventListener('click', () => {
    document.getElementById('input-events-file').value = '';
    browserController.setSelectedEventFile('');
    currentPreviewFile = null;
    setStatus('Single events file cleared. Scan will use BIDS folder.', 'info');
    scanEvents(false);
  });
  document.getElementById('input-events-file').addEventListener('change', () => {
    // When a specific events.tsv is set manually, immediately refresh preview/columns.
    browserController.setSelectedEventFile(document.getElementById('input-events-file').value.trim());
    currentPreviewFile = null;
    scanEvents(false);
  });
  document.getElementById('select-task').addEventListener('change', () => {
    // Changing task filter should force a fresh random file within that task.
    pendingLaunchTaskFilter = '';
    currentPreviewFile = null;
    scanEvents(false);
  });
  document.getElementById('btn-copy-json').addEventListener('click', copyJSON);
  document.getElementById('preview-row-limit').addEventListener('change', () => scanEvents(false));
  document.getElementById('preview-hide-na-cols').addEventListener('change', () => {
    if (lastScanData) scanPreviewController.renderEventsPreview(lastScanData);
  });
  document.getElementById('btn-tb-browse-select').addEventListener('click', () => {
    browserController.applySelectedBidsPath();
  });
  document.getElementById('btn-ev-browse-select').addEventListener('click', () => {
    browserController.applySelectedEventsFile();
  });

  // Events preview toggle
  document.getElementById('events-preview-toggle').addEventListener('click', () => {
    const body   = document.getElementById('events-preview-body');
    const toggle = document.getElementById('events-preview-toggle');
    const open   = body.style.display === 'none';
    body.style.display   = open ? '' : 'none';
    toggle.classList.toggle('open', open);
  });
  document.getElementById('btn-resample').addEventListener('click', resamplePreview);

  document.querySelectorAll('.btn-add-op').forEach(btn => {
    btn.addEventListener('click', () => addOperation(btn.dataset.op, btn.dataset.cat));
  });

  // Auto-scan if project BIDS folder is pre-filled
  const presetBids = document.getElementById('input-bids-dir').value.trim();
  if (presetBids) scanEvents(false);
  initializeModelSelection();

  function readTransformerLaunchContext() {
    try {
      const raw = sessionStorage.getItem(TRANSFORMER_LAUNCH_CONTEXT_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function getTransformerPayload() {
    return pipelineController.getTransformerPayload();
  }

  function persistPendingTransformerPayload(payload) {
    const value = (payload && typeof payload === 'object' && !Array.isArray(payload))
      ? payload
      : {};
    try {
      sessionStorage.setItem(PENDING_TRANSFORMER_KEY, JSON.stringify(value));
      return { ok: true, usedFallback: false };
    } catch (withSnapshotError) {
      const fallback = { ...value };
      delete fallback.modelSnapshot;
      try {
        sessionStorage.setItem(PENDING_TRANSFORMER_KEY, JSON.stringify(fallback));
        return { ok: true, usedFallback: true };
      } catch (fallbackError) {
        try {
          sessionStorage.removeItem(PENDING_TRANSFORMER_KEY);
        } catch (cleanupError) {
          // Ignore storage cleanup failures.
        }
        return { ok: false, usedFallback: false };
      }
    }
  }

  function applyToModel() {
    const targetModelPath = getSelectedModelPath();
    if (!targetModelPath) {
      setStatus('No target model selected. Choose a model in Target model file first.', 'warning');
      return;
    }

    const outputIssues = collectRequiredOutputIssues();
    if (outputIssues.length) {
      const preview = outputIssues.slice(0, 2).join(' ');
      const suffix = outputIssues.length > 2 ? ` (+${outputIssues.length - 2} more)` : '';
      setStatus(`Set Output name(s) for generated columns before applying. ${preview}${suffix}`, 'warning');
      return;
    }

    const transformations = getTransformerPayload();
    if (!transformations.Instructions.length) {
      setStatus('Add at least one transformer instruction before applying to the model.', 'warning');
      return;
    }

    const generatedColumns = getGeneratedModelXRegressorSuggestions();
    const launchId = String(launchContext?.launchId || '').trim();
    const targetProjectId = String(launchContext?.projectId || CURRENT_PROJECT_ID || '').trim();
    const targetLevels = getTargetLevels();
    const sourceScope = getEffectiveSourceScope();

    if (EMBEDDED_MODE) {
      try {
        try {
          sessionStorage.removeItem(PENDING_TRANSFORMER_KEY);
        } catch (cleanupError) {
          // Ignore stale payload cleanup failures.
        }
        window.parent.postMessage({
          type: TRANSFORMER_APPLIED_EVENT,
          launchId,
          projectId: targetProjectId,
          modelPath: targetModelPath,
          transformations,
          generatedColumns,
          targetLevels,
          sourceScope
        }, window.location.origin);
      } catch (e) {
        setStatus('Transformer payload prepared, but parent editor could not be notified.', 'warning');
        return;
      }
      setStatus(`Transformer applied for ${targetLevels.join(', ')} node level(s). Design Matrix is unchanged; generated outputs are available for manual Model.X selection.`, 'success');
      return;
    }

    const stored = persistPendingTransformerPayload({
      launchId,
      projectId: targetProjectId,
      modelPath: targetModelPath,
      transformations,
      generatedColumns,
      targetLevels,
      sourceScope,
      appliedAt: Date.now()
    });
    if (!stored.ok) {
      setStatus('Could not store transformer payload for model handoff.', 'danger');
      return;
    }

    const baseUrl = targetProjectId
      ? `/analysis/${encodeURIComponent(targetProjectId)}`
      : '/analysis';
    window.location.href = `${baseUrl}#analysis-model-workspace-section`;
  }

  async function initializeModelSelection() {
    await modelSelectionController.initializeModelSelection();
  }

  async function refreshModelCandidates() {
    await modelSelectionController.refreshModelCandidates();
  }

  function getSelectedModelPath() {
    return modelSelectionController.getSelectedModelPath();
  }

  function normalizeNodeLevel(level) {
    const raw = String(level || '').trim().toLowerCase();
    if (!raw) return '';
    return NODE_LEVEL_OPTIONS.find(option => option.toLowerCase() === raw) || '';
  }

  function getSelectedTargetLevel() {
    const raw = String(document.getElementById('select-target-level')?.value || 'Run').trim();
    if (raw === 'All') return 'All';
    return normalizeNodeLevel(raw) || 'Run';
  }

  function getTargetLevels() {
    const selected = getSelectedTargetLevel();
    return selected === 'All' ? [...NODE_LEVEL_OPTIONS] : [selected];
  }

  function getSelectedSourceScope() {
    const raw = String(document.getElementById('select-source-scope')?.value || 'auto').trim().toLowerCase();
    if (['auto', 'events', 'participants', 'combined'].includes(raw)) return raw;
    return 'auto';
  }

  function getEffectiveSourceScope() {
    const selected = getSelectedSourceScope();
    if (selected !== 'auto') return selected;
    const targetLevel = getSelectedTargetLevel();
    if (targetLevel === 'All') return 'combined';
    return targetLevel === 'Run' ? 'events' : 'participants';
  }

  function updateScopeHint() {
    const hint = document.getElementById('scope-hint');
    if (!hint) return;
    const targetLevels = getTargetLevels();
    const sourceScope = getEffectiveSourceScope();
    const targetText = targetLevels.length === NODE_LEVEL_OPTIONS.length
      ? 'all levels'
      : targetLevels.join(', ');
    const sourceText = sourceScope === 'events'
      ? 'events.tsv'
      : sourceScope === 'participants'
        ? 'participants.tsv'
        : 'events.tsv + participants.tsv';
    hint.textContent = `Target: ${targetText}. Active variable source: ${sourceText}.`;
  }

  function updateLaunchContextHint() {
    const hint = document.getElementById('launch-context-hint');
    if (!hint) return;

    if (!launchNodeLevel && !launchTaskFilter) {
      hint.textContent = '';
      hint.classList.add('d-none');
      return;
    }

    const selectedLevel = getSelectedTargetLevel();
    if (launchNodeLevel && selectedLevel !== launchNodeLevel) {
      hint.textContent = '';
      hint.classList.add('d-none');
      return;
    }

    const parts = [];
    if (launchNodeLevel) {
      parts.push(`target level ${launchNodeLevel}`);
    }
    if (launchTaskFilter) {
      parts.push(`task ${launchTaskFilter}`);
    }

    if (!parts.length) {
      hint.textContent = '';
      hint.classList.add('d-none');
      return;
    }

    hint.textContent = `Preselected from active model: ${parts.join(' and ')}.`;
    hint.classList.remove('d-none');
  }

  function normalizeLaunchTaskFilter(context) {
    const directTask = String(context?.taskFilter || '').trim();
    if (directTask) return directTask;

    const inputTasks = Array.isArray(context?.inputTasks)
      ? context.inputTasks.map(task => String(task || '').trim()).filter(Boolean)
      : [];
    return inputTasks.length === 1 ? inputTasks[0] : '';
  }

  function getRequestedTaskFilter() {
    const taskSel = document.getElementById('select-task');
    const selectedTask = String(taskSel?.value || '').trim();
    return selectedTask || pendingLaunchTaskFilter;
  }

  function mergeColumnValueMaps(left, right) {
    const merged = {};
    Object.entries(left || {}).forEach(([key, values]) => {
      merged[key] = normalizeStringArray(values);
    });
    Object.entries(right || {}).forEach(([key, values]) => {
      const prior = merged[key] || [];
      merged[key] = Array.from(new Set([...prior, ...normalizeStringArray(values)]));
    });
    return merged;
  }

  // ================================================================
  // STATUS
  // ================================================================
  function setStatus(msg, type = 'info') {
    const el = document.getElementById('scan-status');
    el.textContent = msg;
    el.className = `alert alert-${type} py-1 small mt-2 mb-0`;
    el.style.display = 'block';
    if (type === 'success') setTimeout(() => { el.style.display = 'none'; }, 4000);
  }

  function scheduleLiveModelValidation() {
    modelSelectionController.scheduleLiveModelValidation();
  }

  async function scanEvents(forceNewPreview = false) {
    await scanPreviewController.scanEvents(forceNewPreview);
  }

  async function resamplePreview() {
    await scanPreviewController.resamplePreview();
  }

  // ================================================================
  // COLUMNS POOL
  // ================================================================
  function renderColumnsPool() {
    return columnsController.renderColumnsPool();
  }

  function getSelectableColumns() {
    return columnsController.getSelectableColumns();
  }

  function getGeneratedColumns() {
    return columnsController.getGeneratedColumns();
  }

  function getGeneratedModelXRegressorSuggestions() {
    return columnsController.getGeneratedModelXRegressorSuggestions();
  }

  function getColumnDomain(name) {
    return columnsController.getColumnDomain(name);
  }

  function refreshPipelineColumnValues() {
    return columnsController.refreshPipelineColumnValues();
  }

  function normalizeColumnList(value) {
    return columnsController.normalizeColumnList(value);
  }

  function addOperation(opType, cat) {
    return pipelineController.addOperation(opType, cat);
  }

  function getOperationCategory(opType) {
    if (MUNGE_OPERATION_NAMES.has(opType)) return 'munge';
    if (COMPUTE_OPERATION_NAMES.has(opType)) return 'compute';
    return '';
  }
  function updateGeneratedJSON() {
    return pipelineController.updateGeneratedJSON();
  }

  function collectRequiredOutputIssues() {
    return pipelineController.collectRequiredOutputIssues();
  }

  function copyJSON() {
    return pipelineController.copyJSON();
  }

  function extractOpsFromCard(card) {
    return pipelineController.extractOpsFromCard(card);
  }

  async function maybeBootstrapPipelineFromModel(force = false) {
    return pipelineController.maybeBootstrapPipelineFromModel(force, launchContext);
  }

  // ================================================================
  // BIDS FOLDER BROWSER
  // ================================================================
  async function openBidsBrowser() {
    await browserController.openBidsBrowser();
  }

  // ================================================================
  // EVENTS FILE BROWSER
  // ================================================================
  async function openEventsBrowser() {
    await browserController.openEventsBrowser();
  }

  // ================================================================
  // UTILS
  // ================================================================
  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  function escAttr(s) { return escHtml(s); }

})();
