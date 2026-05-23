
(function(){
  const $ = (sel,root=document)=>root.querySelector(sel);
  const CURRENT_PROJECT_ID = "";
  const TRANSFORMER_LAUNCH_CONTEXT_KEY = 'bidspm.transformerLaunchContext';
  const TRANSFORMER_APPLIED_EVENT = 'bidspm-transformer-applied';
  const PENDING_TRANSFORMER_KEY = 'bidspm.pendingTransformerModel';
  let model = null;
  window.modelEditorDraft = null;
  let modelEditorBidsTasks = Array.isArray(window.modelEditorBidsTasks)
    ? window.modelEditorBidsTasks
    : [];
  window.modelEditorBidsTasks = modelEditorBidsTasks;
  window.modelEditorInterestRegressors = Array.isArray(window.modelEditorInterestRegressors)
    ? window.modelEditorInterestRegressors
    : [];
  window.modelEditorEventSamples = (window.modelEditorEventSamples && typeof window.modelEditorEventSamples === 'object')
    ? window.modelEditorEventSamples
    : { trial_type: [], condition: [] };
  window.modelEditorConfoundColumns = Array.isArray(window.modelEditorConfoundColumns)
    ? window.modelEditorConfoundColumns
    : [];
  window.modelEditorTransRotConfounds = Array.isArray(window.modelEditorTransRotConfounds)
    ? window.modelEditorTransRotConfounds
    : [];
  window.modelEditorParticipantsInfo = (window.modelEditorParticipantsInfo && typeof window.modelEditorParticipantsInfo === 'object')
    ? window.modelEditorParticipantsInfo
    : { columns: [], categorical_columns: [], numeric_columns: [], sample_values: {}, numeric_stats: {}, sample_status: 'missing-dir' };
  window.modelEditorGroupByOptions = (Array.isArray(window.modelEditorGroupByOptions) && window.modelEditorGroupByOptions.length)
    ? window.modelEditorGroupByOptions
    : ['subject'];
  let modelEditorInputEntityValues = (window.modelEditorInputEntityValues && typeof window.modelEditorInputEntityValues === 'object')
    ? window.modelEditorInputEntityValues
    : {};
  const previewValidationState = window.__modelPreviewValidationState && typeof window.__modelPreviewValidationState === 'object'
    ? window.__modelPreviewValidationState
    : { timer: null, runId: 0 };
  window.__modelPreviewValidationState = previewValidationState;
  window.modelEditorInputEntityValues = modelEditorInputEntityValues;
  let attemptedBidsDirAutofill = false;
  let attemptedFmriprepDirAutofill = false;
  window.showModelTechnicalPaths = Boolean(window.showModelTechnicalPaths);
  window.modelEditorOpenPaths = window.modelEditorOpenPaths instanceof Set
    ? window.modelEditorOpenPaths
    : new Set();
  window.modelEditorPendingOpenPaths = window.modelEditorPendingOpenPaths instanceof Set
    ? window.modelEditorPendingOpenPaths
    : new Set();
  let editorMode = 'full'; // 'full' or 'friendly'
  let rawMode = false;
  let rawModeReturnEditor = 'full';

  function readPendingTransformerPayload() {
    try {
      const raw = sessionStorage.getItem(PENDING_TRANSFORMER_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function extendInterestRegressorPool(names) {
    const normalized = normalizeStringArray(names);
    if (!normalized.length) return;
    window.modelEditorInterestRegressors = Array.from(new Set([
      ...normalizeStringArray(window.modelEditorInterestRegressors),
      ...normalized
    ]));
  }

  function consumePendingTransformerPayload(targetModelPath) {
    const payload = readPendingTransformerPayload();
    if (!payload || !model || typeof model !== 'object') return null;

    const payloadProjectId = String(payload.projectId || '').trim();
    const currentProjectId = String(CURRENT_PROJECT_ID || '').trim();
    if (payloadProjectId && currentProjectId && payloadProjectId !== currentProjectId) {
      return null;
    }

    const payloadModelPath = String(payload.modelPath || '').trim();
    const normalizedTargetPath = String(targetModelPath || '').trim();
    if (payloadModelPath && normalizedTargetPath && payloadModelPath !== normalizedTargetPath) {
      return null;
    }

    sessionStorage.removeItem(PENDING_TRANSFORMER_KEY);

    const generatedColumns = normalizeStringArray(payload.generatedColumns);
    const instructions = Array.isArray(payload.transformations?.Instructions)
      ? structuredClone(payload.transformations.Instructions)
      : [];
    const runNodes = Array.isArray(model.Nodes)
      ? model.Nodes.filter(node => node && typeof node === 'object' && String(node.Level || '').trim() === 'Run')
      : [];

    if (!runNodes.length) {
      return {
        tone: 'warning',
        message: 'Pending transformer output found, but the model has no Run-level nodes to apply it to.'
      };
    }

    runNodes.forEach(node => {
      const existingTransformations = (node.Transformations && typeof node.Transformations === 'object' && !Array.isArray(node.Transformations))
        ? node.Transformations
        : {};
      const existingGenerated = normalizeStringArray(existingTransformations.GeneratedColumns);
      node.Transformations = {
        ...existingTransformations,
        Transformer: payload.transformations?.Transformer || 'pybids-transforms-v1',
        Instructions: instructions,
        GeneratedColumns: Array.from(new Set([...existingGenerated, ...generatedColumns]))
      };
    });

    extendInterestRegressorPool(generatedColumns);

    return {
      tone: 'success',
      message: `Applied transformer pipeline to ${runNodes.length} Run-level node(s) with ${generatedColumns.length} generated variable(s). Save Model to persist it.`
    };
  }

  function getCurrentModelPathValue() {
    const input = document.getElementById('model-path-input');
    return String(input?.value || modelPath || '').trim();
  }

  function getTransformerBuilderUrl() {
    const projectId = String(CURRENT_PROJECT_ID || '').trim();
    const baseUrl = projectId
      ? `/transformer-builder/${encodeURIComponent(projectId)}`
      : '/transformer-builder';
    return `${baseUrl}?embedded=1`;
  }

  function prepareTransformerLaunchContext(nodeIndex = null) {
    const payload = {
      projectId: String(CURRENT_PROJECT_ID || '').trim(),
      modelPath: getCurrentModelPathValue(),
      bidsDir: String(document.getElementById('input-BIDS_DIR')?.value || '').trim(),
      nodeIndex: Number.isInteger(nodeIndex) ? nodeIndex : null
    };
    try {
      sessionStorage.setItem(TRANSFORMER_LAUNCH_CONTEXT_KEY, JSON.stringify(payload));
    } catch (e) {
      // Ignore storage failures; builder can still be used with manual inputs.
    }
  }

  async function applyPendingTransformerIntoCurrentModel(modelPathHint = '') {
    const targetPath = String(modelPathHint || getCurrentModelPathValue()).trim();
    if (!targetPath || !model || typeof model !== 'object') return false;

    const result = consumePendingTransformerPayload(targetPath);
    if (!result) return false;

    modelEditorDraft = model;
    await refreshModelEditorHintData(model);
    renderModelStructure();
    renderNodeList();
    currentSelection = { type: 'model' };
    window.currentSelection = currentSelection;
    selectedLabel.textContent = 'Model Workspace';
    selectedMeta.textContent = 'Edit input filters, node pipelines, edges and contrasts below.';
    if (typeof window.renderModelAccordionEditor === 'function') window.renderModelAccordionEditor();
    refreshRawEditorFromSelection();
    setStatus(result.message, result.tone || 'success');
    return true;
  }

  window.prepareModelEditorTransformerLaunchContext = prepareTransformerLaunchContext;
  window.getModelEditorTransformerBuilderUrl = getTransformerBuilderUrl;
  window.modelEditorInlineTransformerNodeIdx = Number.isInteger(window.modelEditorInlineTransformerNodeIdx)
    ? window.modelEditorInlineTransformerNodeIdx
    : null;

  window.addEventListener('message', async (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data && typeof event.data === 'object' ? event.data : null;
    if (!data || data.type !== TRANSFORMER_APPLIED_EVENT) return;

    const applied = await applyPendingTransformerIntoCurrentModel(String(data.modelPath || '').trim());
    if (!applied) {
      setStatus('Transformer payload received but could not be applied to the currently loaded model.', 'warning');
    }
  });
  let currentSelection = { type: 'model' };
  window.currentSelection = currentSelection;

  const MODEL_NUISANCE_RX = /^(framewise_displacement|trans_[xyz]|rot_[xyz]|a_comp_cor|dvars|std_dvars|non_steady_state_outlier|cosine\d*|white_matter|csf|global_signal)/;
  const DEFAULT_TRANS_ROT_REGRESSORS = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z'];

  let modelPath = new URLSearchParams(window.location.search).get('path') || '';
  // Spec-aligned guided input keys from BEP002 v1.0.0-rc1 section 3.1:
  // minimally task/run/session/subject, plus space sourced from fMRIPrep derivatives.
  const INPUT_ENTITY_OPTIONS = [
    {key: 'task', hint: 'Task label (e.g. motor or motor,stroop)'},
    {key: 'run', hint: 'Run index (e.g. 1 or 1,2)'},
    {key: 'session', hint: 'Session label (e.g. 01 or 01,02)'},
    {key: 'subject', hint: 'Subject label (e.g. 01 or 01,02)'},
    {key: 'space', hint: 'fMRIPrep space (e.g. MNI152NLin2009cAsym)'}
  ];
  const MODEL_TOP_LEVEL_SPEC = [
    { key: 'Name', required: true },
    { key: 'BIDSModelVersion', required: true },
    { key: 'Description', required: false },
    { key: 'Input', required: false },
    { key: 'Nodes', required: true },
    { key: 'Edges', required: false }
  ];
  const NODE_FIELD_SPEC = ['Level', 'Name', 'GroupBy', 'Transformations', 'Model', 'Contrasts', 'DummyContrasts'];
  const NODE_LEVEL_OPTIONS = ['Run', 'Session', 'Subject', 'Dataset'];
  const GROUPBY_RESERVED_OPTIONS = ['run', 'session', 'subject', 'contrast'];
  const DATASET_DRIVEN_INPUT_KEYS = new Set(['task', 'run', 'session', 'subject', 'space']);
  const nodeListEl = document.getElementById('node-list');
  const selectedLabel = document.getElementById('selected-node-label');
  const selectedMeta = document.getElementById('selected-node-meta');
  const friendlyEditor = document.getElementById('friendly-editor');
  const rawEditor = document.getElementById('raw-editor');
  const statusEl = document.getElementById('editor-status');
  const rawToggleBtn = document.getElementById('btn-toggle-raw');
  let currentNodeIndex = null;

  function setStatus(html, tone='info'){
    statusEl.innerHTML = `<div class="alert alert-${tone} py-1 x-small mb-0">${html}</div>`;
  }

  function setRawMode(active){
    rawMode = Boolean(active);
    rawEditor.style.display = rawMode ? 'block' : 'none';
    friendlyEditor.style.display = rawMode ? 'none' : 'block';
    if (rawToggleBtn) rawToggleBtn.textContent = rawMode ? 'Workflow View' : 'Raw JSON';
  }

  function ensureSelectionDrivenRightPane(){
    if (editorMode !== 'full') return;
    const shell = document.getElementById('model-editor-shell');
    const trans = document.getElementById('transformations-editor');
    editorMode = 'friendly';
    if (shell) shell.style.display = 'none';
    if (trans) trans.style.display = 'block';
  }

  function getCurrentSelectionLabel(){
    if (!currentSelection || currentSelection.type === 'model') return 'model';
    if (currentSelection.type === 'modelField') return `Model.${currentSelection.field}`;
    if (currentSelection.type === 'nodeField') {
      const idx = Number(currentSelection.idx);
      const node = Array.isArray(model?.Nodes) ? model.Nodes[idx] : null;
      const nodeName = node?.Name || `node #${idx + 1}`;
      return `Node ${nodeName}.${currentSelection.field}`;
    }
    return 'model';
  }

  function getCurrentSelectionValue(){
    if (!model) return null;
    if (!currentSelection || currentSelection.type === 'model') return model;
    if (currentSelection.type === 'modelField') return model[currentSelection.field];
    if (currentSelection.type === 'nodeField') {
      const nodes = Array.isArray(model.Nodes) ? model.Nodes : [];
      const node = nodes[currentSelection.idx];
      return node ? node[currentSelection.field] : null;
    }
    return model;
  }

  function applyRawValueToSelection(parsed){
    if (!currentSelection || currentSelection.type === 'model') {
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Model JSON must be an object');
      }
      model = parsed;
      modelEditorDraft = model;
      return;
    }

    if (currentSelection.type === 'modelField') {
      model[currentSelection.field] = parsed;
      return;
    }

    if (currentSelection.type === 'nodeField') {
      const nodes = Array.isArray(model.Nodes) ? model.Nodes : [];
      const node = nodes[currentSelection.idx];
      if (!node) throw new Error('Selected node no longer exists');
      node[currentSelection.field] = parsed;
    }
  }

  function refreshRawEditorFromSelection(){
    if (!rawMode) return;
    const value = getCurrentSelectionValue();
    rawEditor.value = JSON.stringify(value === undefined ? null : value, null, 2);
  }

  function rerenderCurrentSelection(){
    if (!model) return;
    if (currentSelection?.type === 'nodeField') {
      selectNodeField(currentSelection.idx, currentSelection.field);
      return;
    }
    if (currentSelection?.type === 'modelField') {
      selectModelField(currentSelection.field);
      return;
    }
    selectedLabel.textContent = 'Model';
    selectedMeta.textContent = 'Select a field from the left panel.';
    friendlyEditor.innerHTML = '<div class="small text-muted">Select a model field from the left panel, or use Raw JSON to edit the entire model.</div>';
  }

  setRawMode(false);

  async function fetchModel(path){
    // Show loading state in full editor
    const accEditor = document.getElementById('model-editor-accordion');
    if (accEditor) accEditor.innerHTML = '<div class="text-center py-4"><span class="spinner-border spinner-border-sm text-primary me-2"></span><span class="text-muted">Loading model…</span></div>';
    const summaryPanel = document.getElementById('model-editor-summary');
    if (summaryPanel) summaryPanel.classList.add('d-none');
    try{
      const res = await fetch(`/file_content?path=${encodeURIComponent(path)}`);
      if(!res.ok) throw new Error('Failed to load file');
      const txt = await res.text();
      model = JSON.parse(txt);
      // mirror into full-editor draft
      modelEditorDraft = model;
      const pendingTransformerResult = consumePendingTransformerPayload(path);
      const pathLabel = document.getElementById('model-editor-path');
      if(pathLabel) pathLabel.textContent = path;
      await refreshInputEntityOptions(false);
      await refreshModelEditorHintData(model);
      renderModelStructure();
      renderNodeList();
      // reset selection to show all sections, then render full editor
      currentSelection = { type: 'model' };
      window.currentSelection = currentSelection;
      selectedLabel.textContent = 'Model Workspace';
      selectedMeta.textContent = 'Edit input filters, node pipelines, edges and contrasts below.';
      if (typeof window.renderModelAccordionEditor === 'function') window.renderModelAccordionEditor();
      refreshRawEditorFromSelection();
      if (pendingTransformerResult?.message) {
        setStatus(pendingTransformerResult.message, pendingTransformerResult.tone || 'success');
      } else {
        setStatus('Model loaded.', 'success');
      }
    }catch(e){
      model = null;
      nodeListEl.innerHTML = '';
      friendlyEditor.innerHTML = '';
      rawEditor.value = '';
      setStatus('Load failed: ' + e.message, 'danger');
    }
  }

  async function refreshInputEntityOptions(showStatusMessage = false){
    await refreshDatasetInputEntities(false);
    await refreshSpaceInputOptions(false);

    if (showStatusMessage) {
      const counts = ['task', 'run', 'session', 'subject', 'space']
        .map(k => (Array.isArray(modelEditorInputEntityValues[k]) ? modelEditorInputEntityValues[k].length : 0));
      const total = counts.reduce((a, b) => a + b, 0);
      if (total > 0) {
        setStatus(`Loaded input options: task(${counts[0]}), run(${counts[1]}), session(${counts[2]}), subject(${counts[3]}), space(${counts[4]}).`, 'success');
      } else {
        setStatus('No input options detected. Check BIDS and fMRIPrep folder paths.', 'warning');
      }
    }

    if (selectedLabel && selectedLabel.textContent === 'Model — Input') {
      renderInputFieldEditor();
    }
  }

  async function refreshDatasetInputEntities(showStatusMessage = false){
    await ensureBidsDirAutofill();
    const bidsInput = document.getElementById('input-BIDS_DIR');
    const bidsDir = bidsInput ? bidsInput.value.trim() : '';

    if(!bidsDir){
      modelEditorInputEntityValues = {
        ...modelEditorInputEntityValues,
        task: [],
        run: [],
        session: [],
        subject: []
      };
      modelEditorBidsTasks = [];
      window.modelEditorGroupByOptions = ['subject'];
      window.modelEditorInputEntityValues = modelEditorInputEntityValues;
      window.modelEditorBidsTasks = modelEditorBidsTasks;
      return;
    }

    try {
      const res = await fetch(`/api/bids_entities?path=${encodeURIComponent(bidsDir)}`);
      if(!res.ok) throw new Error('dataset query failed');
      const payload = await res.json();
      const values = payload && payload.values ? payload.values : {};

      const normalizedValues = {};
      Object.entries(values).forEach(([key, raw]) => {
        if (Array.isArray(raw)) normalizedValues[key] = raw;
      });
      ['task', 'run', 'session', 'subject'].forEach(key => {
        if (!Array.isArray(normalizedValues[key])) normalizedValues[key] = [];
      });
      modelEditorInputEntityValues = {
        ...modelEditorInputEntityValues,
        task: normalizedValues.task,
        run: normalizedValues.run,
        session: normalizedValues.session,
        subject: normalizedValues.subject
      };
      modelEditorBidsTasks = [...normalizedValues.task];
      window.modelEditorGroupByOptions = (Array.isArray(payload?.groupby_options) && payload.groupby_options.length)
        ? payload.groupby_options
        : ['subject'];
      window.modelEditorInputEntityValues = modelEditorInputEntityValues;
      window.modelEditorBidsTasks = modelEditorBidsTasks;
    } catch (e) {
      modelEditorInputEntityValues = {
        ...modelEditorInputEntityValues,
        task: [],
        run: [],
        session: [],
        subject: []
      };
      modelEditorBidsTasks = [];
      window.modelEditorGroupByOptions = ['subject'];
      window.modelEditorInputEntityValues = modelEditorInputEntityValues;
      window.modelEditorBidsTasks = modelEditorBidsTasks;
    }
  }

  async function refreshSpaceInputOptions(showStatusMessage = false){
    await ensureFmriprepDirAutofill();
    const prepInput = document.getElementById('input-FMRIPREP_DIR');
    const prepDir = prepInput ? prepInput.value.trim() : '';

    if (!prepDir) {
      modelEditorInputEntityValues = {
        ...modelEditorInputEntityValues,
        space: []
      };
      window.modelEditorInputEntityValues = modelEditorInputEntityValues;
      if (showStatusMessage) {
        setStatus('Set fMRIPrep folder to load available spaces.', 'warning');
      }
      return;
    }

    const tasks = inputValueAsSelection(model?.Input?.task).filter(Boolean);
    let url = `/get_fmriprep_spaces?path=${encodeURIComponent(prepDir)}`;
    tasks.forEach(t => { url += `&tasks=${encodeURIComponent(t)}`; });

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error('space query failed');
      const spaces = await res.json();
      modelEditorInputEntityValues = {
        ...modelEditorInputEntityValues,
        space: Array.isArray(spaces) ? spaces : []
      };
      window.modelEditorInputEntityValues = modelEditorInputEntityValues;
      if (showStatusMessage) {
        setStatus(`Loaded ${modelEditorInputEntityValues.space.length} spaces from fMRIPrep.`, 'success');
      }
    } catch (e) {
      modelEditorInputEntityValues = {
        ...modelEditorInputEntityValues,
        space: []
      };
      window.modelEditorInputEntityValues = modelEditorInputEntityValues;
      if (showStatusMessage) {
        setStatus('Could not read fMRIPrep spaces: ' + e.message, 'warning');
      }
    }
  }

  async function ensureBidsDirAutofill(){
    const bidsInput = document.getElementById('input-BIDS_DIR');
    if (!bidsInput) return;
    if (bidsInput.value.trim()) return;
    if (attemptedBidsDirAutofill) return;
    attemptedBidsDirAutofill = true;

    try {
      const res = await fetch('/load_config_file?path=config/config.json');
      if (!res.ok) return;
      const cfg = await res.json();
      const candidate = cfg && typeof cfg.BIDS_DIR === 'string' ? cfg.BIDS_DIR.trim() : '';
      if (candidate) bidsInput.value = candidate;
    } catch (e) {
      // Leave empty if config cannot be loaded.
    }
  }

  async function ensureFmriprepDirAutofill(){
    const prepInput = document.getElementById('input-FMRIPREP_DIR');
    if (!prepInput) return;
    if (prepInput.value.trim()) return;
    if (attemptedFmriprepDirAutofill) return;
    attemptedFmriprepDirAutofill = true;

    try {
      const res = await fetch('/load_config_file?path=config/config.json');
      if (!res.ok) return;
      const cfg = await res.json();
      const candidate = cfg && typeof cfg.FMRIPREP_DIR === 'string' ? cfg.FMRIPREP_DIR.trim() : '';
      if (candidate) prepInput.value = candidate;
    } catch (e) {
      // Leave empty if config cannot be loaded.
    }
  }

  function isLikelyNuisanceRegressor(value){
    if (typeof value !== 'string') return false;
    return MODEL_NUISANCE_RX.test(value.trim());
  }

  function emptyParticipantsInfo(){
    return {
      columns: [],
      categorical_columns: [],
      numeric_columns: [],
      sample_values: {},
      numeric_stats: {},
      sample_status: 'missing-dir'
    };
  }

  function confoundColumnExists(columnName, confoundColumns){
    const normalized = String(columnName || '').trim();
    if (!normalized) return false;
    return confoundColumns.some(col => {
      const candidate = String(col || '').trim();
      return candidate === normalized || candidate.startsWith(`${normalized}_`);
    });
  }

  async function refreshModelEditorHintData(explicitModelContent = null){
    const bidsDir = document.getElementById('input-BIDS_DIR')?.value?.trim() || '';
    const prepDir = document.getElementById('input-FMRIPREP_DIR')?.value?.trim() || '';

    if (!bidsDir) {
      window.modelEditorInterestRegressors = [];
      window.modelEditorEventSamples = { trial_type: [], condition: [] };
      window.modelEditorParticipantsInfo = emptyParticipantsInfo();
      if (!prepDir) {
        window.modelEditorConfoundColumns = [];
        window.modelEditorTransRotConfounds = [];
      }
      return;
    }

    try {
      const response = await fetch('/api/model_hints', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_content: explicitModelContent || modelEditorDraft || model || {},
          bids_dir: bidsDir,
          fmriprep_dir: prepDir
        })
      });

      const data = await response.json();
      if (data.error) {
        window.modelEditorInterestRegressors = [];
        window.modelEditorEventSamples = { trial_type: [], condition: [] };
        window.modelEditorParticipantsInfo = emptyParticipantsInfo();
        if (!prepDir) {
          window.modelEditorConfoundColumns = [];
          window.modelEditorTransRotConfounds = [];
        }
        return;
      }

      const sample = data?.dataset?.events?.sample_values || {};
      const trialValues = normalizeStringArray(sample.trial_type);
      const conditionValues = normalizeStringArray(sample.condition);
      window.modelEditorEventSamples = {
        trial_type: trialValues,
        condition: conditionValues
      };

      const trialRegs = trialValues.map(v => `trial_type.${v}`);
      const conditionRegs = conditionValues.map(v => `condition.${v}`);
      window.modelEditorInterestRegressors = Array.from(new Set([...trialRegs, ...conditionRegs])).filter(Boolean);

      const confounds = data?.dataset?.confounds || {};
      window.modelEditorConfoundColumns = normalizeStringArray(confounds.columns);
      window.modelEditorTransRotConfounds = normalizeStringArray(confounds.trans_rot_present);
      window.modelEditorParticipantsInfo = (data?.dataset?.participants && typeof data.dataset.participants === 'object')
        ? data.dataset.participants
        : emptyParticipantsInfo();
    } catch (e) {
      window.modelEditorInterestRegressors = [];
      window.modelEditorEventSamples = { trial_type: [], condition: [] };
      window.modelEditorParticipantsInfo = emptyParticipantsInfo();
      if (!prepDir) {
        window.modelEditorConfoundColumns = [];
        window.modelEditorTransRotConfounds = [];
      }
    }
  }

  window.refreshSpaceInputOptions = refreshSpaceInputOptions;
  window.refreshModelEditorHintData = refreshModelEditorHintData;

  function inputValueAsSelection(value){
    if (Array.isArray(value)) return value.map(v => String(v));
    if (value === undefined || value === null || value === '') return [];
    return [String(value)];
  }

  function summarizeTopLevelValue(key, value){
    if (key === 'Nodes' || key === 'Edges') {
      return `count: ${Array.isArray(value) ? value.length : 0}`;
    }
    if (key === 'Input') {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        const keys = Object.keys(value);
        return keys.length ? keys.join(', ') : '<empty>';
      }
      return '<none>';
    }
    if (value === undefined || value === null || value === '') return '<empty>';
    return String(value).slice(0, 80);
  }

  function summarizeNodeField(node, field){
    const value = node ? node[field] : undefined;
    if (field === 'Level' || field === 'Name') return value || '<empty>';
    if (field === 'GroupBy') return Array.isArray(value) && value.length ? value.join(', ') : '<empty>';
    if (field === 'Transformations') {
      const count = Array.isArray(value?.Instructions) ? value.Instructions.length : 0;
      if (!value) return '<none>';
      return `${value.Transformer || 'transformer?'} (${count} instruction${count === 1 ? '' : 's'})`;
    }
    if (field === 'Model') {
      const type = value && typeof value === 'object' ? (value.Type || 'type?') : '<none>';
      const xCount = Array.isArray(value?.X) ? value.X.length : 0;
      return `${type}, X=${xCount}`;
    }
    if (field === 'Contrasts') return Array.isArray(value) ? `${value.length} contrast${value.length === 1 ? '' : 's'}` : '<none>';
    if (field === 'DummyContrasts') return value && typeof value === 'object' ? (value.Test || 'configured') : '<none>';
    return value === undefined ? '<none>' : String(value);
  }

  function renderModelStructure(){
    const container = document.getElementById('model-structure');
    if(!container) return;
    container.innerHTML = '';
    if(!model){ container.innerHTML = '<div class="text-muted small">No model loaded</div>'; return; }

    const list = document.createElement('div');
    list.className = 'list-group list-group-flush small';

    function addItem(title, desc, handler, required = false){
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'list-group-item list-group-item-action py-1';
      const titleEl = document.createElement('div');
      titleEl.className = 'fw-bold';
      titleEl.textContent = required ? `${title} *` : title;
      const descEl = document.createElement('div');
      descEl.className = 'text-muted small';
      descEl.textContent = desc || '';
      btn.appendChild(titleEl);
      btn.appendChild(descEl);
      if(handler) btn.addEventListener('click', handler);
      list.appendChild(btn);
    }

    MODEL_TOP_LEVEL_SPEC
      .filter(spec => spec.key !== 'Nodes' && spec.key !== 'Edges')
      .forEach(spec => {
        addItem(
          spec.key,
          summarizeTopLevelValue(spec.key, model[spec.key]),
          ()=> selectModelField(spec.key),
          spec.required
        );
      });

    // Nodes + node subfields from spec section 2.2
    const nodes = Array.isArray(model.Nodes) ? model.Nodes : [];
    const nodesHeader = document.createElement('div');
    nodesHeader.className = 'list-group-item py-1';
    nodesHeader.innerHTML = `<div class="fw-bold">Nodes *</div><div class="text-muted small">count: ${nodes.length}</div>`;
    list.appendChild(nodesHeader);

    if(nodes.length === 0){
      const empty = document.createElement('div');
      empty.className = 'list-group-item py-1 text-muted small';
      empty.textContent = 'No nodes available.';
      list.appendChild(empty);
    } else {
      nodes.forEach((node, idx) => {
        const nodeBlock = document.createElement('div');
        nodeBlock.className = 'list-group-item py-1';

        const nodeBtn = document.createElement('button');
        nodeBtn.type = 'button';
        nodeBtn.className = 'btn btn-link p-0 text-start w-100 small fw-bold';
        nodeBtn.textContent = `${node.Level || 'Run'} · ${node.Name || `node #${idx+1}`}`;
        nodeBtn.addEventListener('click', ()=> selectNode(idx));
        nodeBlock.appendChild(nodeBtn);

        const fieldList = document.createElement('div');
        fieldList.className = 'list-group list-group-flush mt-1';

        NODE_FIELD_SPEC.forEach(field => {
          const fieldBtn = document.createElement('button');
          fieldBtn.type = 'button';
          fieldBtn.className = 'list-group-item list-group-item-action py-1 small border-0 ps-2';
          fieldBtn.textContent = `${field}: ${summarizeNodeField(node, field)}`;
          fieldBtn.addEventListener('click', (event)=>{
            event.preventDefault();
            event.stopPropagation();
            selectNodeField(idx, field);
          });
          fieldList.appendChild(fieldBtn);
        });

        nodeBlock.appendChild(fieldList);
        list.appendChild(nodeBlock);
      });
    }

    const edgesSpec = MODEL_TOP_LEVEL_SPEC.find(spec => spec.key === 'Edges');
    if (edgesSpec) {
      addItem(
        edgesSpec.key,
        summarizeTopLevelValue(edgesSpec.key, model[edgesSpec.key]),
        ()=> selectModelField(edgesSpec.key),
        edgesSpec.required
      );
    }

    container.appendChild(list);
  }

  function selectModelField(field){
    currentNodeIndex = null;
    currentSelection = { type: 'modelField', field };
    window.currentSelection = currentSelection;
    selectedLabel.textContent = `Model — ${field}`;
    selectedMeta.textContent = '';
    if (editorMode === 'full') {
      if (typeof window.renderModelAccordionEditor === 'function') window.renderModelAccordionEditor();
      return;
    }
    friendlyEditor.innerHTML = '';
    const value = model ? model[field] : null;
    if(field === 'Input'){
      renderInputFieldEditor();
      refreshInputEntityOptions(false);
      refreshRawEditorFromSelection();
      return;
    }
    if(['Name','BIDSModelVersion','Description'].includes(field)){
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-control';
      input.value = value || '';
      input.addEventListener('change', ()=>{ model[field] = input.value; renderModelStructure(); setStatus('Field updated', 'info'); });
      friendlyEditor.appendChild(input);
    } else {
      const ta = document.createElement('textarea');
      ta.className = 'form-control font-monospace';
      ta.style.minHeight = '220px';
      ta.value = JSON.stringify(value || {}, null, 2);
      ta.addEventListener('change', ()=>{
        try{ model[field] = JSON.parse(ta.value); renderModelStructure(); setStatus('Field updated', 'info'); }catch(e){ setStatus('Invalid JSON', 'danger'); }
      });
      friendlyEditor.appendChild(ta);
    }
    refreshRawEditorFromSelection();
  }

  function stringifyInputValue(value){
    if (Array.isArray(value)) return value.join(', ');
    if (value === null || value === undefined) return '';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function coerceTokenValue(token, key){
    const trimmed = token.trim();
    if (!trimmed) return '';
    if (trimmed === 'true') return true;
    if (trimmed === 'false') return false;
    if (/^-?\d+(\.\d+)?$/.test(trimmed) && ['run','echo','split','chunk','resolution','density'].includes(key)) {
      return Number(trimmed);
    }
    return trimmed;
  }

  function parseInputValue(raw, key){
    const text = (raw || '').trim();
    if (!text) return undefined;

    if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) {
      try { return JSON.parse(text); } catch(e) { /* fall through */ }
    }

    if (text.includes(',')) {
      const parts = text.split(',').map(t => coerceTokenValue(t, key)).filter(v => v !== '');
      return parts;
    }
    return coerceTokenValue(text, key);
  }

  function renderInputFieldEditor(){
    if(!model || typeof model !== 'object') return;
    if(!model.Input || typeof model.Input !== 'object' || Array.isArray(model.Input)) model.Input = {};

    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex flex-column gap-3';

    const help = document.createElement('div');
    help.className = 'small text-muted';
    help.innerHTML = 'Set top-level <strong>Input</strong> filters (<strong>task, run, session, subject</strong>) and <strong>space</strong> from fMRIPrep derivatives.';
    wrapper.appendChild(help);

    const commonCard = document.createElement('div');
    commonCard.className = 'border rounded p-3 bg-white';
    const commonTitle = document.createElement('div');
    commonTitle.className = 'fw-bold mb-2';
    commonTitle.textContent = 'Common BIDS Input Options';
    commonCard.appendChild(commonTitle);

    const commonGrid = document.createElement('div');
    commonGrid.className = 'row g-2';
    let renderedOptionCount = 0;
    INPUT_ENTITY_OPTIONS.forEach(opt => {
      const datasetChoices = Array.isArray(modelEditorInputEntityValues[opt.key])
        ? modelEditorInputEntityValues[opt.key]
        : [];
      const sourceLabel = opt.key === 'space' ? 'fMRIPrep' : 'dataset';
      const hasModelKey = Object.prototype.hasOwnProperty.call(model.Input, opt.key);
      if (!datasetChoices.length && !hasModelKey) return;

      renderedOptionCount += 1;
      const col = document.createElement('div');
      col.className = 'col-12';
      const label = document.createElement('label');
      label.className = 'form-label small mb-1';
      label.textContent = opt.key;
      const isCoreDatasetEntity = DATASET_DRIVEN_INPUT_KEYS.has(opt.key);
      const showDropdown = datasetChoices.length > 0;

      col.appendChild(label);

      if (showDropdown) {
        const modelValues = inputValueAsSelection(model.Input[opt.key]);
        const datasetValuesAsText = datasetChoices.map(v => String(v));
        const legacyModelValues = modelValues.filter(v => !datasetValuesAsText.includes(v));
        const allChoices = [...datasetValuesAsText, ...legacyModelValues];
        const selectedSet = new Set(modelValues);

        const select = document.createElement('select');
        select.className = 'form-select form-select-sm';
        select.multiple = true;
        select.size = Math.min(8, Math.max(3, allChoices.length || 3));

        if (allChoices.length) {
          allChoices.forEach((choice, idx) => {
            const optEl = document.createElement('option');
            optEl.value = choice;
            const isLegacy = idx >= datasetValuesAsText.length;
            optEl.textContent = isLegacy ? `${choice} (from model)` : choice;
            if (selectedSet.has(optEl.value)) optEl.selected = true;
            select.appendChild(optEl);
          });
        } else {
          const emptyOpt = document.createElement('option');
          emptyOpt.disabled = true;
          emptyOpt.selected = true;
          emptyOpt.textContent = 'No values found in dataset';
          select.appendChild(emptyOpt);
        }

        const info = document.createElement('div');
        info.className = 'small text-muted mt-1';

        function updateInfo() {
          const selectedCount = Array.from(select.selectedOptions).filter(o => !o.disabled).length;
          info.textContent = datasetChoices.length
            ? `${selectedCount} selected out of ${datasetChoices.length} ${sourceLabel} values`
            : (opt.key === 'space'
                ? 'Set a valid fMRIPrep folder to load available spaces.'
                : 'Set a valid BIDS folder to load available values.');
        }

        select.addEventListener('change', ()=>{
          const selected = Array.from(select.selectedOptions)
            .filter(o => !o.disabled)
            .map(o => coerceTokenValue(o.value, opt.key));
          if (!selected.length) delete model.Input[opt.key];
          else model.Input[opt.key] = selected;
          renderModelStructure();
          updateInfo();
          setStatus('Input updated', 'info');
          if (opt.key === 'task') {
            refreshSpaceInputOptions(false).then(async () => {
              await refreshModelEditorHintData(model);
              if (selectedLabel && selectedLabel.textContent === 'Model — Input') renderInputFieldEditor();
              if (typeof window.renderModelAccordionEditor === 'function' && editorMode === 'full') {
                window.renderModelAccordionEditor();
              }
            });
          }
        });

        const actions = document.createElement('div');
        actions.className = 'd-flex gap-2 mt-1';
        const useAll = document.createElement('button');
        useAll.type = 'button';
        useAll.className = 'btn btn-outline-secondary btn-sm';
        useAll.textContent = 'Select all';
        useAll.disabled = !datasetChoices.length;

        const clearAll = document.createElement('button');
        clearAll.type = 'button';
        clearAll.className = 'btn btn-outline-secondary btn-sm';
        clearAll.textContent = 'Clear';
        clearAll.disabled = !datasetChoices.length;

        useAll.addEventListener('click', ()=>{
          Array.from(select.options).forEach(o => { if (!o.disabled) o.selected = true; });
          model.Input[opt.key] = Array.from(select.options)
            .filter(o => !o.disabled)
            .map(o => coerceTokenValue(String(o.value), opt.key));
          renderModelStructure();
          updateInfo();
          setStatus('Input updated', 'info');
          if (opt.key === 'task') {
            refreshSpaceInputOptions(false).then(async () => {
              await refreshModelEditorHintData(model);
              if (selectedLabel && selectedLabel.textContent === 'Model — Input') renderInputFieldEditor();
              if (typeof window.renderModelAccordionEditor === 'function' && editorMode === 'full') {
                window.renderModelAccordionEditor();
              }
            });
          }
        });

        clearAll.addEventListener('click', ()=>{
          Array.from(select.options).forEach(o => { if (!o.disabled) o.selected = false; });
          delete model.Input[opt.key];
          renderModelStructure();
          updateInfo();
          setStatus('Input updated', 'info');
          if (opt.key === 'task') {
            refreshSpaceInputOptions(false).then(async () => {
              await refreshModelEditorHintData(model);
              if (selectedLabel && selectedLabel.textContent === 'Model — Input') renderInputFieldEditor();
              if (typeof window.renderModelAccordionEditor === 'function' && editorMode === 'full') {
                window.renderModelAccordionEditor();
              }
            });
          }
        });

        actions.appendChild(useAll);
        actions.appendChild(clearAll);

        col.appendChild(select);
        col.appendChild(actions);
        col.appendChild(info);

        if (legacyModelValues.length) {
          const legacyNote = document.createElement('div');
          legacyNote.className = 'small text-warning mt-1';
          legacyNote.textContent = 'Some values come from the model and were not found in the current dataset.';
          col.appendChild(legacyNote);
        }

        updateInfo();
      } else {
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control form-control-sm';
        input.placeholder = opt.hint;
        input.value = stringifyInputValue(model.Input[opt.key]);
        input.addEventListener('change', ()=>{
          const parsed = parseInputValue(input.value, opt.key);
          if (parsed === undefined) delete model.Input[opt.key];
          else model.Input[opt.key] = parsed;
          renderModelStructure();
          setStatus('Input updated', 'info');
          if (opt.key === 'task') {
            refreshSpaceInputOptions(false).then(async () => {
              await refreshModelEditorHintData(model);
              if (selectedLabel && selectedLabel.textContent === 'Model — Input') renderInputFieldEditor();
              if (typeof window.renderModelAccordionEditor === 'function' && editorMode === 'full') {
                window.renderModelAccordionEditor();
              }
            });
          }
        });
        col.appendChild(input);

        if (isCoreDatasetEntity) {
          const note = document.createElement('div');
          note.className = 'small text-warning mt-1';
          note.textContent = opt.key === 'space'
            ? 'No fMRIPrep spaces detected; showing current model value only.'
            : 'No dataset values detected for this key; showing current model value only.';
          col.appendChild(note);
        }
      }

      commonGrid.appendChild(col);
    });

    if (renderedOptionCount === 0) {
      const empty = document.createElement('div');
      empty.className = 'col-12 small text-muted';
      empty.textContent = 'No Input entities detected yet. Set BIDS and fMRIPrep folders to populate task/run/session/subject/space options.';
      commonGrid.appendChild(empty);
    }

    commonCard.appendChild(commonGrid);
    wrapper.appendChild(commonCard);

    const knownKeys = new Set(INPUT_ENTITY_OPTIONS.map(o => o.key));
    const customKeys = Object.keys(model.Input).filter(k => !knownKeys.has(k));

    const customCard = document.createElement('div');
    customCard.className = 'border rounded p-3 bg-white';
    const customTitle = document.createElement('div');
    customTitle.className = 'fw-bold mb-2';
    customTitle.textContent = 'Additional Input Filters (Advanced / Non-core)';
    customCard.appendChild(customTitle);

    const customList = document.createElement('div');
    customList.className = 'd-flex flex-column gap-2';
    customKeys.forEach(key => {
      const row = document.createElement('div');
      row.className = 'd-flex gap-2 align-items-start';

      const keyInput = document.createElement('input');
      keyInput.type = 'text';
      keyInput.className = 'form-control form-control-sm';
      keyInput.value = key;

      const valueInput = document.createElement('input');
      valueInput.type = 'text';
      valueInput.className = 'form-control form-control-sm';
      valueInput.value = stringifyInputValue(model.Input[key]);
      valueInput.placeholder = 'value or comma-separated values';

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-sm btn-outline-danger';
      removeBtn.innerHTML = '<i class="fas fa-trash"></i>';

      keyInput.addEventListener('change', ()=>{
        const newKey = keyInput.value.trim();
        const oldVal = model.Input[key];
        delete model.Input[key];
        if (newKey) model.Input[newKey] = oldVal;
        renderModelStructure();
        renderInputFieldEditor();
      });

      valueInput.addEventListener('change', ()=>{
        const useKey = keyInput.value.trim() || key;
        const parsed = parseInputValue(valueInput.value, useKey);
        if (parsed === undefined) delete model.Input[useKey];
        else model.Input[useKey] = parsed;
        renderModelStructure();
        setStatus('Input updated', 'info');
      });

      removeBtn.addEventListener('click', ()=>{
        const useKey = keyInput.value.trim() || key;
        delete model.Input[useKey];
        renderModelStructure();
        renderInputFieldEditor();
        setStatus('Custom input filter removed', 'info');
      });

      row.appendChild(keyInput);
      row.appendChild(valueInput);
      row.appendChild(removeBtn);
      customList.appendChild(row);
    });
    customCard.appendChild(customList);

    const addRow = document.createElement('div');
    addRow.className = 'd-flex gap-2 mt-2';
    const newKey = document.createElement('input');
    newKey.type = 'text';
    newKey.className = 'form-control form-control-sm';
    newKey.placeholder = 'new key';
    const newVal = document.createElement('input');
    newVal.type = 'text';
    newVal.className = 'form-control form-control-sm';
    newVal.placeholder = 'value';
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-sm btn-outline-secondary';
    addBtn.textContent = 'Add';
    addBtn.addEventListener('click', ()=>{
      const k = newKey.value.trim();
      if(!k) return;
      const parsed = parseInputValue(newVal.value, k);
      model.Input[k] = parsed === undefined ? '' : parsed;
      renderModelStructure();
      renderInputFieldEditor();
      setStatus('Custom input filter added', 'info');
    });
    addRow.appendChild(newKey);
    addRow.appendChild(newVal);
    addRow.appendChild(addBtn);
    customCard.appendChild(addRow);

    const preview = document.createElement('pre');
    preview.className = 'small p-2 bg-light border rounded mt-2';
    preview.style.maxHeight = '160px';
    preview.style.overflow = 'auto';
    preview.textContent = JSON.stringify(model.Input, null, 2);
    customCard.appendChild(preview);

    wrapper.appendChild(customCard);

    friendlyEditor.innerHTML = '';
    friendlyEditor.appendChild(wrapper);
  }

  function renderNodeList(){
    nodeListEl.innerHTML = '';
    const nodes = Array.isArray(model?.Nodes) ? model.Nodes : [];
    if(nodes.length === 0){
      nodeListEl.innerHTML = '<div class="text-muted small">No nodes in model.</div>';
      return;
    }
    nodes.forEach((node, idx) => {
      const name = node.Name || `node #${idx+1}`;
      const lvl = node.Level || 'Run';
      const item = document.createElement('button');
      item.type='button';
      item.className = 'list-group-item list-group-item-action';
      item.textContent = `${lvl} · ${name}`;
      item.addEventListener('click', ()=> selectNode(idx));
      nodeListEl.appendChild(item);
    });
  }

  function cloneJson(value){
    return JSON.parse(JSON.stringify(value));
  }

  function defaultNodeFieldValue(field, idx = 0){
    if (field === 'Level') return 'Run';
    if (field === 'Name') return `node_${idx+1}`;
    if (field === 'GroupBy') return ['run', 'subject'];
    if (field === 'Transformations') return { Transformer: 'pybids-transforms-v1', Instructions: [] };
    if (field === 'Model') return { Type: 'glm', X: [1] };
    if (field === 'Contrasts') return [];
    if (field === 'DummyContrasts') return { Test: 't' };
    return null;
  }

  function getModelEditorParticipantsInfo(){
    return (window.modelEditorParticipantsInfo && typeof window.modelEditorParticipantsInfo === 'object')
      ? window.modelEditorParticipantsInfo
      : emptyParticipantsInfo();
  }

  function slugifyNodeToken(value){
    return String(value || '')
      .trim()
      .replace(/\s+/g, '_')
      .replace(/[^A-Za-z0-9_]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .toLowerCase();
  }

  function getUniqueNodeName(baseName){
    const normalizedBase = String(baseName || '').trim() || 'node';
    const existing = new Set(
      (Array.isArray(model?.Nodes) ? model.Nodes : [])
        .map(node => String(node?.Name || '').trim().toLowerCase())
        .filter(Boolean)
    );
    if (!existing.has(normalizedBase.toLowerCase())) return normalizedBase;
    for (let idx = 2; idx < 1000; idx += 1) {
      const candidate = `${normalizedBase}_${idx}`;
      if (!existing.has(candidate.toLowerCase())) return candidate;
    }
    return `${normalizedBase}_${Date.now().toString().slice(-4)}`;
  }

  function applyDatasetNodePreset(node, preset, options = {}){
    const participantsInfo = getModelEditorParticipantsInfo();
    const categoricalColumns = normalizeStringArray(participantsInfo.categorical_columns);
    const numericColumns = normalizeStringArray(participantsInfo.numeric_columns);
    const sampleValues = (participantsInfo.sample_values && typeof participantsInfo.sample_values === 'object')
      ? participantsInfo.sample_values
      : {};

    const groupVariable = String(options.groupVariable || categoricalColumns[0] || '').trim();
    const covariate = String(options.covariate || numericColumns[0] || '').trim();
    const allLevels = normalizeStringArray(sampleValues[groupVariable]);
    const groupA = String(options.groupA || allLevels[0] || '').trim();
    const groupB = String(options.groupB || allLevels.find(level => level !== groupA) || allLevels[0] || '').trim();

    node.Level = 'Dataset';
    if (!node.Model || typeof node.Model !== 'object' || Array.isArray(node.Model)) node.Model = {};
    node.Model = {
      ...node.Model,
      Type: String(node.Model.Type || 'glm').trim() || 'glm',
      X: ['1']
    };
    delete node.Model.HRF;
    delete node.Transformations;

    let message = 'Applied dataset preset.';
    let tone = 'success';

    if (preset === 'one_sample_all') {
      node.GroupBy = ['contrast'];
      node.Description = 'one sample t-test: averaging across all subjects';
      node.DummyContrasts = { Test: 't' };
      node.Contrasts = [];
      return { message: 'Applied all-subject one-sample dataset preset.', tone, suggestedName: 'dataset_level' };
    }

    if (preset === 'one_sample_by_group') {
      node.GroupBy = groupVariable ? ['contrast', groupVariable] : ['contrast'];
      node.Description = groupVariable
        ? `one sample t-test for each ${groupVariable} group`
        : 'one sample t-test for each group';
      node.DummyContrasts = { Test: 't' };
      node.Contrasts = [];
      message = groupVariable
        ? `Applied one-sample-by-group preset using ${groupVariable}.`
        : 'Added one-sample-by-group scaffold. Select a participants.tsv grouping variable to finish setup.';
      tone = groupVariable ? 'success' : 'warning';
      return { message, tone, suggestedName: groupVariable ? `within_${slugifyNodeToken(groupVariable)}_group` : 'within_group' };
    }

    if (preset === 'two_sample_groups') {
      node.GroupBy = ['contrast'];
      node.Model.X = groupVariable ? ['1', groupVariable] : ['1'];
      node.Description = groupVariable
        ? `2 sample t-test between ${groupVariable} groups`
        : '2 sample t-test between groups';
      delete node.DummyContrasts;
      node.Contrasts = [];
      if (groupVariable && groupA && groupB && groupA !== groupB) {
        node.Contrasts = [{
          Name: `${slugifyNodeToken(groupA)}_gt_${slugifyNodeToken(groupB)}`,
          ConditionList: [`${groupVariable}.${groupA}`, `${groupVariable}.${groupB}`],
          Weights: [1, -1],
          Test: 't'
        }];
        message = `Applied two-sample group comparison using ${groupVariable}.`;
        tone = 'success';
      } else {
        message = groupVariable
          ? `Added two-sample scaffold using ${groupVariable}. Pick the two group values in Node.Model to finish the contrast.`
          : 'Added two-sample scaffold. Select a categorical participants.tsv variable to finish setup.';
        tone = 'warning';
      }
      return { message, tone, suggestedName: groupVariable ? `between_${slugifyNodeToken(groupVariable)}_groups` : 'between_groups' };
    }

    if (preset === 'one_way_anova') {
      node.GroupBy = ['contrast'];
      node.Model.X = groupVariable ? ['1', groupVariable] : ['1'];
      node.Description = groupVariable
        ? `one way ANOVA across ${groupVariable}`
        : 'one way ANOVA across groups';
      delete node.DummyContrasts;
      node.Contrasts = [];
      if (groupVariable && allLevels.length >= 2) {
        node.Contrasts = [{
          Name: `average_across_${slugifyNodeToken(groupVariable) || 'groups'}`,
          ConditionList: allLevels.map(level => `${groupVariable}.${level}`),
          Weights: allLevels.map(() => 1),
          Test: 't'
        }];
        message = `Applied one-way ANOVA scaffold using ${groupVariable}.`;
        tone = 'success';
      } else {
        message = groupVariable
          ? `Added one-way ANOVA scaffold using ${groupVariable}. More observed group values are needed to build the contrast automatically.`
          : 'Added one-way ANOVA scaffold. Select a categorical participants.tsv variable to finish setup.';
        tone = 'warning';
      }
      return { message, tone, suggestedName: groupVariable ? `${slugifyNodeToken(groupVariable)}_anova` : 'one_way_anova' };
    }

    if (preset === 'linear_regression') {
      node.GroupBy = ['contrast'];
      node.Model.X = covariate ? ['1', covariate] : ['1'];
      node.Description = covariate
        ? `linear regression with ${covariate}`
        : 'linear regression with numeric covariate';
      delete node.DummyContrasts;
      node.Contrasts = [];
      if (covariate) {
        node.Contrasts = [
          {
            Name: `${slugifyNodeToken(covariate)}_positive`,
            ConditionList: [covariate],
            Weights: [1],
            Test: 't'
          },
          {
            Name: `${slugifyNodeToken(covariate)}_negative`,
            ConditionList: [covariate],
            Weights: [-1],
            Test: 't'
          }
        ];
        message = `Applied linear regression preset using ${covariate}.`;
        tone = 'success';
      } else {
        message = 'Added linear regression scaffold. Select a numeric participants.tsv covariate to finish setup.';
        tone = 'warning';
      }
      return { message, tone, suggestedName: covariate ? `${slugifyNodeToken(covariate)}_regression` : 'dataset_regression' };
    }

    return { message, tone, suggestedName: 'dataset_level' };
  }

  function buildNodeFromPreset(preset){
    if (preset === 'subject_fixed') {
      return {
        node: {
          Level: 'Subject',
          Name: getUniqueNodeName('subject_level'),
          GroupBy: ['contrast', 'subject'],
          Model: { Type: 'glm', X: ['1'] },
          DummyContrasts: { Test: 't' },
          Contrasts: []
        },
        message: 'Added subject-level fixed-effects node.',
        tone: 'success',
        selectField: 'Model'
      };
    }

    if (preset === 'dataset_basic') {
      return {
        node: {
          Level: 'Dataset',
          Name: getUniqueNodeName('dataset_level'),
          GroupBy: ['contrast'],
          Model: { Type: 'glm', X: ['1'] },
          DummyContrasts: { Test: 't' },
          Contrasts: []
        },
        message: 'Added dataset-level node. Configure second-level preset in Node.Model.',
        tone: 'success',
        selectField: 'Model',
        forceFriendly: true
      };
    }

    if (['one_sample_all', 'one_sample_by_group', 'two_sample_groups', 'one_way_anova', 'linear_regression'].includes(preset)) {
      const node = {
        Level: 'Dataset',
        Name: '',
        GroupBy: ['contrast'],
        Model: { Type: 'glm', X: ['1'] },
        DummyContrasts: { Test: 't' },
        Contrasts: []
      };
      const result = applyDatasetNodePreset(node, preset);
      node.Name = getUniqueNodeName(result.suggestedName || 'dataset_level');
      return {
        node,
        message: result.message,
        tone: result.tone,
        selectField: 'Model',
        forceFriendly: true
      };
    }

    const node = cloneJson(defaultArrayItemForPath('Nodes'));
    node.Name = getUniqueNodeName('run_level');
    return {
      node,
      message: 'Added run-level node.',
      tone: 'success',
      selectField: 'Model'
    };
  }

  function normalizeStringArray(value){
    if (!Array.isArray(value)) return [];
    return value.map(v => String(v).trim()).filter(Boolean);
  }

  function ensureNodeModelObject(node, idx){
    if (!node.Model || typeof node.Model !== 'object' || Array.isArray(node.Model)) {
      node.Model = cloneJson(defaultNodeFieldValue('Model', idx));
    }
    if (!Array.isArray(node.Model.X)) node.Model.X = [];
    node.Model.X = normalizeStringArray(node.Model.X);
    if (typeof node.Model.Type !== 'string' || !node.Model.Type.trim()) {
      node.Model.Type = 'glm';
    }
    return node.Model;
  }

  function renderDatasetNodeModelFieldEditor(node, idx, modelObj){
    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex flex-column gap-3';

    const participantsInfo = getModelEditorParticipantsInfo();
    const categoricalColumns = normalizeStringArray(participantsInfo.categorical_columns);
    const numericColumns = normalizeStringArray(participantsInfo.numeric_columns);
    const sampleValues = (participantsInfo.sample_values && typeof participantsInfo.sample_values === 'object')
      ? participantsInfo.sample_values
      : {};
    modelObj.X = normalizeStringArray(modelObj.X);
    if (!modelObj.X.length) modelObj.X = ['1'];

    function rerender(message, tone = 'info'){
      renderModelStructure();
      renderNodeModelFieldEditor(node, idx);
      setStatus(message, tone);
    }

    function createFieldRow(labelText){
      const row = document.createElement('div');
      row.className = 'd-flex flex-column gap-1';
      const label = document.createElement('label');
      label.className = 'form-label small mb-0';
      label.textContent = labelText;
      row.appendChild(label);
      return { row, label };
    }

    function setModelX(values){
      const normalized = normalizeStringArray(values);
      modelObj.X = normalized.length ? normalized : ['1'];
    }

    const help = document.createElement('div');
    help.className = 'small text-muted';
    help.innerHTML = 'Dataset-level nodes use <strong>participants.tsv</strong> variables for grouping and covariates. Apply a preset, then refine <strong>Contrasts</strong> and <strong>Edges.Filter.contrast</strong> if you need a more specific second-level model.';
    wrapper.appendChild(help);

    const typeRow = createFieldRow('Model Type');
    const typeInput = document.createElement('input');
    typeInput.type = 'text';
    typeInput.className = 'form-control form-control-sm';
    typeInput.value = modelObj.Type || 'glm';
    typeInput.addEventListener('change', ()=>{
      modelObj.Type = (typeInput.value || '').trim() || 'glm';
      renderModelStructure();
      setStatus('Node Model.Type updated', 'info');
    });
    typeRow.row.appendChild(typeInput);
    wrapper.appendChild(typeRow.row);

    const presetCard = document.createElement('div');
    presetCard.className = 'border rounded p-3 bg-white d-flex flex-column gap-2';
    const presetTitle = document.createElement('div');
    presetTitle.className = 'small fw-bold';
    presetTitle.textContent = 'Second-Level Presets';
    presetCard.appendChild(presetTitle);

    const presetHint = document.createElement('div');
    presetHint.className = 'small text-muted';
    presetHint.textContent = 'Presets update Node.Model, Node.GroupBy, and dataset-level contrasts together.';
    presetCard.appendChild(presetHint);

    const presetRow = createFieldRow('Preset');
    const presetSelect = document.createElement('select');
    presetSelect.className = 'form-select form-select-sm';
    [
      ['one_sample_all', 'one sample t-test: all subjects'],
      ['one_sample_by_group', 'one sample t-test: one model per group'],
      ['two_sample_groups', '2 samples t-test: compare 2 groups'],
      ['one_way_anova', 'one way ANOVA: compare several groups'],
      ['linear_regression', 'linear regression: numeric covariate']
    ].forEach(([value, label])=>{
      const opt = document.createElement('option');
      opt.value = value;
      opt.textContent = label;
      presetSelect.appendChild(opt);
    });
    presetRow.row.appendChild(presetSelect);
    presetCard.appendChild(presetRow.row);

    const defaultGroupVar = node.GroupBy.find(value => categoricalColumns.includes(String(value)))
      || modelObj.X.find(value => categoricalColumns.includes(String(value)))
      || categoricalColumns[0]
      || '';
    const defaultCovariate = modelObj.X.find(value => numericColumns.includes(String(value)))
      || numericColumns[0]
      || '';

    const groupVarRow = createFieldRow('Grouping Variable');
    const groupVarSelect = document.createElement('select');
    groupVarSelect.className = 'form-select form-select-sm';
    const emptyGroupVar = document.createElement('option');
    emptyGroupVar.value = '';
    emptyGroupVar.textContent = categoricalColumns.length ? 'Select participant column' : 'No categorical participant columns found';
    groupVarSelect.appendChild(emptyGroupVar);
    categoricalColumns.forEach(column => {
      const opt = document.createElement('option');
      opt.value = column;
      opt.textContent = column;
      groupVarSelect.appendChild(opt);
    });
    groupVarSelect.value = defaultGroupVar;
    groupVarRow.row.appendChild(groupVarSelect);
    presetCard.appendChild(groupVarRow.row);

    const covariateRow = createFieldRow('Numeric Covariate');
    const covariateSelect = document.createElement('select');
    covariateSelect.className = 'form-select form-select-sm';
    const emptyCovariate = document.createElement('option');
    emptyCovariate.value = '';
    emptyCovariate.textContent = numericColumns.length ? 'Select numeric participant column' : 'No numeric participant columns found';
    covariateSelect.appendChild(emptyCovariate);
    numericColumns.forEach(column => {
      const opt = document.createElement('option');
      opt.value = column;
      opt.textContent = column;
      covariateSelect.appendChild(opt);
    });
    covariateSelect.value = defaultCovariate;
    covariateRow.row.appendChild(covariateSelect);
    presetCard.appendChild(covariateRow.row);

    const groupALevelRow = createFieldRow('Group A');
    const groupALevelSelect = document.createElement('select');
    groupALevelSelect.className = 'form-select form-select-sm';
    groupALevelRow.row.appendChild(groupALevelSelect);
    presetCard.appendChild(groupALevelRow.row);

    const groupBLevelRow = createFieldRow('Group B');
    const groupBLevelSelect = document.createElement('select');
    groupBLevelSelect.className = 'form-select form-select-sm';
    groupBLevelRow.row.appendChild(groupBLevelSelect);
    presetCard.appendChild(groupBLevelRow.row);

    const valuesHint = document.createElement('div');
    valuesHint.className = 'small text-muted';
    presetCard.appendChild(valuesHint);

    function updateGroupLevelOptions(){
      const groupVariable = groupVarSelect.value;
      const levels = normalizeStringArray(sampleValues[groupVariable]);
      groupALevelSelect.innerHTML = '';
      groupBLevelSelect.innerHTML = '';

      if (!levels.length) {
        const emptyA = document.createElement('option');
        emptyA.value = '';
        emptyA.textContent = 'No sample values found';
        const emptyB = emptyA.cloneNode(true);
        groupALevelSelect.appendChild(emptyA);
        groupBLevelSelect.appendChild(emptyB);
        valuesHint.textContent = groupVariable
          ? `No sample values were found for ${groupVariable}.`
          : 'Pick a grouping variable to inspect its observed values.';
        return;
      }

      levels.forEach(level => {
        const optionA = document.createElement('option');
        optionA.value = level;
        optionA.textContent = level;
        groupALevelSelect.appendChild(optionA);

        const optionB = document.createElement('option');
        optionB.value = level;
        optionB.textContent = level;
        groupBLevelSelect.appendChild(optionB);
      });

      groupALevelSelect.value = levels[0] || '';
      groupBLevelSelect.value = levels[1] || levels[0] || '';
      valuesHint.textContent = `${groupVariable} values: ${levels.join(', ')}`;
    }

    function updatePresetVisibility(){
      const preset = presetSelect.value;
      const needsGrouping = ['one_sample_by_group', 'two_sample_groups', 'one_way_anova'].includes(preset);
      const needsTwoGroups = preset === 'two_sample_groups';
      const needsCovariate = preset === 'linear_regression';
      groupVarRow.row.style.display = needsGrouping ? 'flex' : 'none';
      groupALevelRow.row.style.display = needsTwoGroups ? 'flex' : 'none';
      groupBLevelRow.row.style.display = needsTwoGroups ? 'flex' : 'none';
      covariateRow.row.style.display = needsCovariate ? 'flex' : 'none';
      valuesHint.style.display = needsGrouping ? 'block' : 'none';
      if (needsGrouping) updateGroupLevelOptions();
    }

    groupVarSelect.addEventListener('change', updateGroupLevelOptions);
    presetSelect.addEventListener('change', updatePresetVisibility);
    updatePresetVisibility();

    const applyPresetBtn = document.createElement('button');
    applyPresetBtn.type = 'button';
    applyPresetBtn.className = 'btn btn-sm btn-outline-primary align-self-start';
    applyPresetBtn.textContent = 'Apply Preset';
    applyPresetBtn.addEventListener('click', ()=>{
      const result = applyDatasetNodePreset(node, presetSelect.value, {
        groupVariable: groupVarSelect.value.trim(),
        covariate: covariateSelect.value.trim(),
        groupA: groupALevelSelect.value.trim(),
        groupB: groupBLevelSelect.value.trim()
      });
      modelObj = ensureNodeModelObject(node, idx);
      setModelX(modelObj.X);
      rerender(result.message, result.tone || 'success');
    });
    presetCard.appendChild(applyPresetBtn);
    wrapper.appendChild(presetCard);

    const participantsCard = document.createElement('div');
    participantsCard.className = 'border rounded p-3 bg-light-subtle d-flex flex-column gap-2';
    const participantsTitle = document.createElement('div');
    participantsTitle.className = 'small fw-bold';
    participantsTitle.textContent = 'participants.tsv Variables';
    participantsCard.appendChild(participantsTitle);

    const participantsHint = document.createElement('div');
    participantsHint.className = 'small text-muted';
    participantsHint.textContent = participantsInfo.sample_status === 'present'
      ? 'Categorical variables are useful for GroupBy. Numeric variables can be used as regressors in Model.X for covariate analyses.'
      : 'No participants.tsv metadata is available yet. Group comparisons and covariate models depend on participants.tsv columns.';
    participantsCard.appendChild(participantsHint);

    const categoricalText = document.createElement('div');
    categoricalText.className = 'small';
    categoricalText.innerHTML = `<strong>Categorical:</strong> ${categoricalColumns.length ? categoricalColumns.join(', ') : 'none detected'}`;
    participantsCard.appendChild(categoricalText);

    const numericText = document.createElement('div');
    numericText.className = 'small';
    numericText.innerHTML = `<strong>Numeric:</strong> ${numericColumns.length ? numericColumns.join(', ') : 'none detected'}`;
    participantsCard.appendChild(numericText);
    wrapper.appendChild(participantsCard);

    const xCard = document.createElement('div');
    xCard.className = 'border rounded p-3 bg-white d-flex flex-column gap-2';
    const xTitle = document.createElement('div');
    xTitle.className = 'small fw-bold';
    xTitle.textContent = 'Design Matrix Regressors (Model.X)';
    xCard.appendChild(xTitle);

    const xHint = document.createElement('div');
    xHint.className = 'small text-muted';
    xHint.textContent = 'Use drag/drop or click badges to build Model.X. Keep 1 as intercept and add participants.tsv variables as needed.';
    xCard.appendChild(xHint);

    function addDatasetRegressor(value, insertIndex = null) {
      const normalized = String(value || '').trim();
      if (!normalized) return false;
      if (!Array.isArray(modelObj.X)) modelObj.X = [];
      if (modelObj.X.includes(normalized)) {
        setStatus(`Regressor already present: ${normalized}`, 'warning');
        return false;
      }

      if (insertIndex === null || insertIndex === undefined || insertIndex < 0 || insertIndex > modelObj.X.length) {
        modelObj.X.push(normalized);
      } else {
        modelObj.X.splice(insertIndex, 0, normalized);
      }
      rerender('Dataset Model.X updated.', 'info');
      return true;
    }

    function reorderDatasetRegressor(fromIndex, toIndex) {
      if (!Array.isArray(modelObj.X)) return;
      if (fromIndex === toIndex) return;
      if (fromIndex < 0 || fromIndex >= modelObj.X.length) return;
      if (toIndex < 0 || toIndex > modelObj.X.length) return;

      const [moved] = modelObj.X.splice(fromIndex, 1);
      let targetIndex = toIndex;
      if (fromIndex < toIndex) targetIndex -= 1;
      modelObj.X.splice(targetIndex, 0, moved);
      rerender('Regressor order updated.', 'info');
    }

    function applyDroppedDatasetRegressor(event, targetIndex) {
      const sourceIndexRaw = event.dataTransfer.getData('application/x-modelx-index');
      const droppedValue = (event.dataTransfer.getData('application/x-modelx-regressor') || event.dataTransfer.getData('text/plain') || '').trim();

      if (sourceIndexRaw !== '') {
        const sourceIndex = Number(sourceIndexRaw);
        if (!Number.isNaN(sourceIndex)) {
          reorderDatasetRegressor(sourceIndex, targetIndex);
          return;
        }
      }

      if (droppedValue) addDatasetRegressor(droppedValue, targetIndex);
    }

    const datasetRegressorOptions = Array.from(new Set(['1', ...categoricalColumns, ...numericColumns])).filter(Boolean);

    const participantPoolHint = document.createElement('div');
    participantPoolHint.className = 'small text-muted';
    participantPoolHint.textContent = 'participants.tsv variables (drag/click):';
    xCard.appendChild(participantPoolHint);

    const participantPool = document.createElement('div');
    participantPool.className = 'modelx-pool';
    if (!datasetRegressorOptions.length) {
      const emptyPool = document.createElement('div');
      emptyPool.className = 'small text-muted';
      emptyPool.textContent = 'No participants.tsv variables detected yet.';
      participantPool.appendChild(emptyPool);
    } else {
      datasetRegressorOptions.forEach(reg => {
        const badge = document.createElement('button');
        badge.type = 'button';
        badge.className = reg === '1'
          ? 'btn btn-sm btn-outline-secondary modelx-reg-badge'
          : 'btn btn-sm btn-outline-primary modelx-reg-badge';
        badge.textContent = reg;
        badge.draggable = true;
        badge.addEventListener('click', () => addDatasetRegressor(reg));
        badge.addEventListener('dragstart', (event) => {
          event.dataTransfer.effectAllowed = 'copy';
          event.dataTransfer.setData('application/x-modelx-regressor', reg);
          event.dataTransfer.setData('text/plain', reg);
        });
        participantPool.appendChild(badge);
      });
    }
    xCard.appendChild(participantPool);

    const xActions = document.createElement('div');
    xActions.className = 'd-flex flex-wrap gap-2';

    const addInterceptBtn = document.createElement('button');
    addInterceptBtn.type = 'button';
    addInterceptBtn.className = 'btn btn-sm btn-outline-secondary';
    addInterceptBtn.textContent = 'Add Intercept (1)';
    addInterceptBtn.addEventListener('click', ()=>{
      addDatasetRegressor('1', 0);
    });
    xActions.appendChild(addInterceptBtn);

    const addGroupVariableBtn = document.createElement('button');
    addGroupVariableBtn.type = 'button';
    addGroupVariableBtn.className = 'btn btn-sm btn-outline-secondary';
    addGroupVariableBtn.textContent = 'Add Group Variable';
    addGroupVariableBtn.addEventListener('click', ()=>{
      const groupVariable = groupVarSelect.value.trim();
      if (!groupVariable) {
        setStatus('Select a grouping variable first.', 'warning');
        return;
      }
      addDatasetRegressor(groupVariable);
    });
    xActions.appendChild(addGroupVariableBtn);

    const addCovariateBtn = document.createElement('button');
    addCovariateBtn.type = 'button';
    addCovariateBtn.className = 'btn btn-sm btn-outline-secondary';
    addCovariateBtn.textContent = 'Add Numeric Covariate';
    addCovariateBtn.addEventListener('click', ()=>{
      const covariate = covariateSelect.value.trim();
      if (!covariate) {
        setStatus('Select a numeric covariate first.', 'warning');
        return;
      }
      addDatasetRegressor(covariate);
    });
    xActions.appendChild(addCovariateBtn);
    xCard.appendChild(xActions);

    const dropZone = document.createElement('div');
    dropZone.className = 'modelx-drop-zone';
    dropZone.addEventListener('dragover', (event) => {
      event.preventDefault();
      dropZone.classList.add('is-over');
    });
    dropZone.addEventListener('dragleave', () => {
      dropZone.classList.remove('is-over');
    });
    dropZone.addEventListener('drop', (event) => {
      event.preventDefault();
      dropZone.classList.remove('is-over');
      applyDroppedDatasetRegressor(event, Array.isArray(modelObj.X) ? modelObj.X.length : 0);
    });

    if (!Array.isArray(modelObj.X) || modelObj.X.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'small text-muted w-100';
      empty.textContent = 'Drop variable badges here to build dataset Model.X.';
      dropZone.appendChild(empty);
    } else {
      modelObj.X.forEach((reg, regIdx) => {
        const chip = document.createElement('div');
        chip.className = 'modelx-chip';
        chip.draggable = true;
        chip.title = 'Drag to reorder';

        chip.addEventListener('dragstart', (event) => {
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('application/x-modelx-index', String(regIdx));
          event.dataTransfer.setData('application/x-modelx-regressor', String(reg));
          event.dataTransfer.setData('text/plain', String(reg));
        });
        chip.addEventListener('dragover', (event) => {
          event.preventDefault();
          chip.classList.add('is-drop-target');
        });
        chip.addEventListener('dragleave', () => chip.classList.remove('is-drop-target'));
        chip.addEventListener('drop', (event) => {
          event.preventDefault();
          event.stopPropagation();
          chip.classList.remove('is-drop-target');
          applyDroppedDatasetRegressor(event, regIdx);
        });
        chip.addEventListener('dragend', () => chip.classList.remove('is-drop-target'));

        const main = document.createElement('div');
        main.className = 'modelx-chip-main';

        const handle = document.createElement('span');
        handle.className = 'modelx-chip-handle';
        handle.innerHTML = '<i class="fas fa-grip-vertical"></i>';
        main.appendChild(handle);

        const label = document.createElement('span');
        label.className = reg === '1'
          ? 'badge text-bg-secondary modelx-chip-label'
          : 'badge bg-primary modelx-chip-label';
        label.textContent = String(reg);
        main.appendChild(label);

        const actions = document.createElement('div');
        actions.className = 'modelx-chip-actions';

        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'modelx-chip-remove';
        delBtn.title = 'Remove regressor';
        delBtn.innerHTML = '<i class="fas fa-times"></i>';
        delBtn.addEventListener('click', () => {
          modelObj.X.splice(regIdx, 1);
          rerender('Regressor removed from dataset Model.X.', 'info');
        });
        actions.appendChild(delBtn);

        chip.appendChild(main);
        chip.appendChild(actions);
        dropZone.appendChild(chip);
      });
    }

    xCard.appendChild(dropZone);
    wrapper.appendChild(xCard);

    const advanced = document.createElement('details');
    advanced.className = 'border rounded p-2';
    const advJsonSummary = document.createElement('summary');
    advJsonSummary.className = 'small fw-bold';
    advJsonSummary.textContent = 'Advanced JSON (Model only)';
    advanced.appendChild(advJsonSummary);

    const advHelp = document.createElement('div');
    advHelp.className = 'small text-muted mt-2';
    advHelp.textContent = 'Use this for uncommon dataset-level designs or to refine what the preset created.';
    advanced.appendChild(advHelp);

    const advTa = document.createElement('textarea');
    advTa.className = 'form-control font-monospace mt-2';
    advTa.style.minHeight = '180px';
    advTa.value = JSON.stringify(modelObj, null, 2);
    advanced.appendChild(advTa);

    const advApply = document.createElement('button');
    advApply.type = 'button';
    advApply.className = 'btn btn-sm btn-outline-secondary mt-2';
    advApply.textContent = 'Apply Advanced JSON';
    advApply.addEventListener('click', ()=>{
      try {
        const parsed = JSON.parse(advTa.value);
        node.Model = parsed;
        ensureNodeModelObject(node, idx);
        renderModelStructure();
        renderNodeModelFieldEditor(node, idx);
        setStatus('Node Model updated from advanced JSON', 'info');
      } catch (e) {
        setStatus('Invalid JSON for Node.Model: ' + e.message, 'danger');
      }
    });
    advanced.appendChild(advApply);
    wrapper.appendChild(advanced);

    return wrapper;
  }

  function renderNodeModelFieldEditor(node, idx){
    const modelObj = ensureNodeModelObject(node, idx);
    if (String(node?.Level || '').trim() === 'Dataset') {
      friendlyEditor.appendChild(renderDatasetNodeModelFieldEditor(node, idx, modelObj));
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex flex-column gap-3';

    const help = document.createElement('div');
    help.className = 'small text-muted';
    help.textContent = 'Friendly editor for Node.Model. Use guided controls for common fields, then Advanced JSON only if needed.';
    wrapper.appendChild(help);

    const typeRow = document.createElement('div');
    typeRow.className = 'd-flex flex-column gap-1';
    const typeLabel = document.createElement('label');
    typeLabel.className = 'form-label small mb-0';
    typeLabel.textContent = 'Model Type';
    const typeInput = document.createElement('input');
    typeInput.type = 'text';
    typeInput.className = 'form-control form-control-sm';
    typeInput.value = modelObj.Type || 'glm';
    typeInput.placeholder = 'glm';
    typeInput.addEventListener('change', ()=>{
      modelObj.Type = (typeInput.value || '').trim() || 'glm';
      renderModelStructure();
      setStatus('Node Model.Type updated', 'info');
    });
    typeRow.appendChild(typeLabel);
    typeRow.appendChild(typeInput);
    wrapper.appendChild(typeRow);

    const xCard = document.createElement('div');
    xCard.className = 'border rounded p-2 bg-white d-flex flex-column gap-2';
    const xTitle = document.createElement('div');
    xTitle.className = 'small fw-bold';
    xTitle.textContent = 'Design Matrix Regressors (Model.X)';
    xCard.appendChild(xTitle);

    const eventSamples = (window.modelEditorEventSamples && typeof window.modelEditorEventSamples === 'object')
      ? window.modelEditorEventSamples
      : { trial_type: [], condition: [] };
    const selectedTasks = normalizeStringArray(modelEditorDraft?.Input?.task);
    const hasSingleSelectedTask = selectedTasks.length === 1;
    const trialTypeRegressors = hasSingleSelectedTask
      ? normalizeStringArray(eventSamples.trial_type).map(v => `trial_type.${v}`)
      : [];
    const conditionRegressors = hasSingleSelectedTask
      ? normalizeStringArray(eventSamples.condition).map(v => `condition.${v}`)
      : [];
    const confoundColumns = normalizeStringArray(window.modelEditorConfoundColumns);
    const transRotConfounds = normalizeStringArray(window.modelEditorTransRotConfounds);

    function normalizeFriendlyHrfVariables(){
      if (!modelObj.HRF || typeof modelObj.HRF !== 'object') return [];
      return normalizeStringArray(modelObj.HRF.Variables);
    }

    function syncFriendlyHrfVariables(){
      if (!modelObj.HRF || typeof modelObj.HRF !== 'object') return;
      const selected = new Set(normalizeStringArray(modelObj.X));
      const kept = normalizeFriendlyHrfVariables().filter(reg => selected.has(reg));
      if (!kept.length) {
        delete modelObj.HRF;
        return;
      }
      modelObj.HRF = {
        ...modelObj.HRF,
        Model: String(modelObj.HRF.Model || 'spm').trim() || 'spm',
        Variables: kept
      };
    }

    function isHrfApplicableRegressor(regressor){
      return String(regressor || '').trim() !== '1';
    }

    function isFriendlyRegressorHrfEnabled(regressor){
      return normalizeFriendlyHrfVariables().includes(String(regressor || '').trim());
    }

    function toggleFriendlyRegressorHrf(regressor){
      const normalized = String(regressor || '').trim();
      if (!normalized) return;
      if (!isHrfApplicableRegressor(normalized)) {
        setStatus('Intercept is not HRF-convolved.', 'info');
        return;
      }

      const currentlyEnabled = isFriendlyRegressorHrfEnabled(normalized);
      if (currentlyEnabled) {
        if (modelObj.HRF && typeof modelObj.HRF === 'object') {
          const nextVars = normalizeFriendlyHrfVariables().filter(reg => reg !== normalized);
          if (nextVars.length) {
            modelObj.HRF.Variables = nextVars;
          } else {
            delete modelObj.HRF;
          }
        }
        rerenderModelX(`HRF off for ${normalized}`, 'info');
        return;
      }

      if (!modelObj.HRF || typeof modelObj.HRF !== 'object') {
        modelObj.HRF = { Model: 'spm', Variables: [] };
      }
      modelObj.HRF.Model = String(modelObj.HRF.Model || 'spm').trim() || 'spm';
      modelObj.HRF.Variables = Array.from(new Set([...normalizeFriendlyHrfVariables(), normalized]));
      rerenderModelX(`HRF on for ${normalized}`, 'info');
    }

    function rerenderModelX(message, tone = 'info'){
      modelObj.X = normalizeStringArray(modelObj.X);
      syncFriendlyHrfVariables();
      renderModelStructure();
      renderNodeModelFieldEditor(node, idx);
      setStatus(message, tone);
    }

    function addModelXRegressor(value, insertIndex = null){
      const normalized = String(value || '').trim();
      if (!normalized) return false;
      if (!Array.isArray(modelObj.X)) modelObj.X = [];
      if (modelObj.X.includes(normalized)) {
        setStatus(`Regressor already present: ${normalized}`, 'warning');
        return false;
      }

      if (insertIndex === null || insertIndex === undefined || insertIndex < 0 || insertIndex > modelObj.X.length) {
        modelObj.X.push(normalized);
      } else {
        modelObj.X.splice(insertIndex, 0, normalized);
      }
      rerenderModelX('Regressor added to Model.X', 'info');
      return true;
    }

    function reorderModelXRegressor(fromIndex, toIndex){
      if (!Array.isArray(modelObj.X)) return;
      if (fromIndex === toIndex) return;
      if (fromIndex < 0 || fromIndex >= modelObj.X.length) return;
      if (toIndex < 0 || toIndex > modelObj.X.length) return;

      const [moved] = modelObj.X.splice(fromIndex, 1);
      let targetIndex = toIndex;
      if (fromIndex < toIndex) targetIndex -= 1;
      modelObj.X.splice(targetIndex, 0, moved);
      rerenderModelX('Regressor order updated', 'info');
    }

    function applyDroppedRegressor(event, targetIndex){
      const sourceIndexRaw = event.dataTransfer.getData('application/x-modelx-index');
      const droppedValue = (event.dataTransfer.getData('application/x-modelx-regressor') || event.dataTransfer.getData('text/plain') || '').trim();

      if (sourceIndexRaw !== '') {
        const sourceIndex = Number(sourceIndexRaw);
        if (!Number.isNaN(sourceIndex)) {
          reorderModelXRegressor(sourceIndex, targetIndex);
          return;
        }
      }

      if (droppedValue) addModelXRegressor(droppedValue, targetIndex);
    }

    const trialPoolCard = document.createElement('div');
    trialPoolCard.className = 'border rounded p-2 bg-light-subtle';
    const trialPoolTitle = document.createElement('div');
    trialPoolTitle.className = 'small fw-bold mb-1';
    trialPoolTitle.textContent = 'Trial Types from events.tsv';
    trialPoolCard.appendChild(trialPoolTitle);

    const trialPoolHint = document.createElement('div');
    trialPoolHint.className = 'small text-muted mb-2';
    trialPoolHint.textContent = hasSingleSelectedTask
      ? 'Drag or click badges into the Design Matrix space below.'
      : 'Select exactly one task in Input.task to load task-specific trial types.';
    trialPoolCard.appendChild(trialPoolHint);

    const trialPool = document.createElement('div');
    trialPool.className = 'modelx-pool';
    if (!trialTypeRegressors.length) {
      const empty = document.createElement('div');
      empty.className = 'small text-muted';
      empty.textContent = hasSingleSelectedTask
        ? 'No trial_type values detected. Check BIDS folder and events files.'
        : 'Task-specific trial types are hidden while zero or multiple tasks are selected.';
      trialPool.appendChild(empty);
    } else {
      trialTypeRegressors.forEach(reg => {
        const badge = document.createElement('button');
        badge.type = 'button';
        badge.className = 'btn btn-sm btn-outline-primary modelx-reg-badge';
        badge.textContent = reg;
        badge.draggable = true;
        badge.addEventListener('click', ()=> addModelXRegressor(reg));
        badge.addEventListener('dragstart', (event)=>{
          event.dataTransfer.effectAllowed = 'copy';
          event.dataTransfer.setData('application/x-modelx-regressor', reg);
          event.dataTransfer.setData('text/plain', reg);
        });
        trialPool.appendChild(badge);
      });
    }
    trialPoolCard.appendChild(trialPool);
    xCard.appendChild(trialPoolCard);

    if (conditionRegressors.length) {
      const condPool = document.createElement('div');
      condPool.className = 'modelx-pool';
      const condLabel = document.createElement('div');
      condLabel.className = 'small text-muted w-100';
      condLabel.textContent = 'Optional condition.* regressors';
      condPool.appendChild(condLabel);
      conditionRegressors.forEach(reg => {
        const badge = document.createElement('button');
        badge.type = 'button';
        badge.className = 'btn btn-sm btn-outline-secondary modelx-reg-badge';
        badge.textContent = reg;
        badge.draggable = true;
        badge.addEventListener('click', ()=> addModelXRegressor(reg));
        badge.addEventListener('dragstart', (event)=>{
          event.dataTransfer.effectAllowed = 'copy';
          event.dataTransfer.setData('application/x-modelx-regressor', reg);
          event.dataTransfer.setData('text/plain', reg);
        });
        condPool.appendChild(badge);
      });
      xCard.appendChild(condPool);
    }

    const nuisanceCard = document.createElement('div');
    nuisanceCard.className = 'border rounded p-2';
    const nuisanceTitle = document.createElement('div');
    nuisanceTitle.className = 'small fw-bold mb-1';
    nuisanceTitle.textContent = 'Regressors of No Interest (fMRIPrep confounds check)';
    nuisanceCard.appendChild(nuisanceTitle);

    const nuisanceHint = document.createElement('div');
    nuisanceHint.className = 'small text-muted mb-2';
    nuisanceHint.textContent = confoundColumns.length
      ? `Detected ${confoundColumns.length} confound columns. Drag or click badges into Design Matrix space.`
      : 'No confounds file detected yet. Set fMRIPrep folder to validate trans/rot columns.';
    nuisanceCard.appendChild(nuisanceHint);

    const nuisanceInModelX = normalizeStringArray(modelObj.X).filter(isLikelyNuisanceRegressor);
    if (nuisanceInModelX.length) {
      const warning = document.createElement('div');
      warning.className = 'alert alert-warning py-1 small mb-2';
      warning.textContent = `${nuisanceInModelX.length} nuisance regressor(s) are currently inside Model.X.`;
      nuisanceCard.appendChild(warning);

      const removeNuisanceBtn = document.createElement('button');
      removeNuisanceBtn.type = 'button';
      removeNuisanceBtn.className = 'btn btn-sm btn-outline-danger mb-2';
      removeNuisanceBtn.textContent = 'Remove nuisance regressors from Model.X';
      removeNuisanceBtn.addEventListener('click', ()=>{
        modelObj.X = normalizeStringArray(modelObj.X).filter(reg => !isLikelyNuisanceRegressor(reg));
        rerenderModelX('Removed nuisance regressors from Model.X.', 'info');
      });
      nuisanceCard.appendChild(removeNuisanceBtn);
    }

    const nuisanceOptions = Array.from(new Set([
      ...DEFAULT_TRANS_ROT_REGRESSORS,
      'framewise_displacement',
      ...transRotConfounds
    ]));
    const nuisanceGrid = document.createElement('div');
    nuisanceGrid.className = 'modelx-pool';

    nuisanceOptions.forEach(reg => {
      const presentInConfounds = confoundColumnExists(reg, confoundColumns) || transRotConfounds.includes(reg);
      const badge = document.createElement('button');
      badge.type = 'button';
      badge.className = presentInConfounds
        ? 'btn btn-sm btn-outline-secondary modelx-reg-badge'
        : 'btn btn-sm btn-outline-danger modelx-reg-badge';
      badge.textContent = presentInConfounds ? reg : `${reg} (missing)`;
      badge.draggable = true;
      badge.addEventListener('click', ()=> addModelXRegressor(reg));
      badge.addEventListener('dragstart', (event)=>{
        event.dataTransfer.effectAllowed = 'copy';
        event.dataTransfer.setData('application/x-modelx-regressor', reg);
        event.dataTransfer.setData('text/plain', reg);
      });
      nuisanceGrid.appendChild(badge);
    });
    nuisanceCard.appendChild(nuisanceGrid);
    xCard.appendChild(nuisanceCard);

    const xListTitle = document.createElement('div');
    xListTitle.className = 'small fw-bold';
    xListTitle.textContent = 'Design Matrix space';
    xCard.appendChild(xListTitle);

    const xList = document.createElement('div');
    xList.className = 'modelx-drop-zone';
    xList.addEventListener('dragover', (event)=>{
      event.preventDefault();
      xList.classList.add('is-over');
    });
    xList.addEventListener('dragleave', ()=>{
      xList.classList.remove('is-over');
    });
    xList.addEventListener('drop', (event)=>{
      event.preventDefault();
      xList.classList.remove('is-over');
      applyDroppedRegressor(event, modelObj.X.length);
    });

    if (!Array.isArray(modelObj.X) || modelObj.X.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'small text-muted w-100';
      empty.textContent = 'Drop trial_type / nuisance badges here to build Model.X. Drag badges to reorder.';
      xList.appendChild(empty);
    } else {
      modelObj.X.forEach((reg, regIdx) => {
        const regChip = document.createElement('div');
        regChip.className = 'modelx-chip';
        regChip.draggable = true;
        regChip.title = 'Drag to reorder';

        regChip.addEventListener('dragstart', (event)=>{
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('application/x-modelx-index', String(regIdx));
          event.dataTransfer.setData('application/x-modelx-regressor', String(reg));
          event.dataTransfer.setData('text/plain', String(reg));
        });
        regChip.addEventListener('dragover', (event)=>{
          event.preventDefault();
          regChip.classList.add('is-drop-target');
        });
        regChip.addEventListener('dragleave', ()=>{
          regChip.classList.remove('is-drop-target');
        });
        regChip.addEventListener('drop', (event)=>{
          event.preventDefault();
          event.stopPropagation();
          regChip.classList.remove('is-drop-target');
          applyDroppedRegressor(event, regIdx);
        });
        regChip.addEventListener('dragend', ()=>{
          regChip.classList.remove('is-drop-target');
        });

        const main = document.createElement('div');
        main.className = 'modelx-chip-main';

        const handle = document.createElement('span');
        handle.className = 'modelx-chip-handle';
        handle.innerHTML = '<i class="fas fa-grip-vertical"></i>';

        const regBadge = document.createElement('span');
        regBadge.className = isLikelyNuisanceRegressor(String(reg))
          ? 'badge text-bg-secondary modelx-chip-label'
          : 'badge bg-primary modelx-chip-label';
        regBadge.textContent = String(reg);

        main.appendChild(handle);
        main.appendChild(regBadge);

        const actions = document.createElement('div');
        actions.className = 'modelx-chip-actions';

        const hrfBtn = document.createElement('button');
        hrfBtn.type = 'button';
        hrfBtn.className = isFriendlyRegressorHrfEnabled(reg)
          ? 'btn btn-sm btn-success'
          : 'btn btn-sm btn-outline-secondary';
        hrfBtn.textContent = isFriendlyRegressorHrfEnabled(reg) ? 'HRF on' : 'HRF off';
        if (isHrfApplicableRegressor(reg)) {
          hrfBtn.addEventListener('click', (event)=>{
            event.stopPropagation();
            toggleFriendlyRegressorHrf(reg);
          });
        } else {
          hrfBtn.disabled = true;
          hrfBtn.textContent = 'HRF n/a';
        }

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'modelx-chip-remove';
        removeBtn.title = 'Remove regressor';
        removeBtn.innerHTML = '<i class="fas fa-times"></i>';
        removeBtn.addEventListener('click', (event)=>{
          event.stopPropagation();
          modelObj.X.splice(regIdx, 1);
          rerenderModelX('Regressor removed', 'info');
        });

        actions.appendChild(hrfBtn);
        actions.appendChild(removeBtn);
        regChip.appendChild(main);
        regChip.appendChild(actions);
        xList.appendChild(regChip);
      });
    }
    xCard.appendChild(xList);

    const advancedCustom = document.createElement('details');
    advancedCustom.className = 'mt-1';
    const advSummary = document.createElement('summary');
    advSummary.className = 'small fw-bold';
    advSummary.textContent = 'Add custom regressor (advanced)';
    advancedCustom.appendChild(advSummary);

    const addCustomRow = document.createElement('div');
    addCustomRow.className = 'd-flex gap-2 mt-2';
    const newReg = document.createElement('input');
    newReg.type = 'text';
    newReg.className = 'form-control form-control-sm';
    newReg.placeholder = 'e.g. custom_modulator';
    const addCustomBtn = document.createElement('button');
    addCustomBtn.type = 'button';
    addCustomBtn.className = 'btn btn-sm btn-outline-secondary';
    addCustomBtn.textContent = 'Add';
    addCustomBtn.addEventListener('click', ()=>{
      const val = (newReg.value || '').trim();
      if (!val) return;
      if (/\s/.test(val)) {
        setStatus('Custom regressor names cannot contain spaces.', 'warning');
        return;
      }
      addModelXRegressor(val);
    });
    addCustomRow.appendChild(newReg);
    addCustomRow.appendChild(addCustomBtn);
    advancedCustom.appendChild(addCustomRow);
    xCard.appendChild(advancedCustom);

    const addInterceptBtn = document.createElement('button');
    addInterceptBtn.type = 'button';
    addInterceptBtn.className = 'btn btn-sm btn-outline-secondary align-self-start';
    addInterceptBtn.textContent = 'Add Intercept (1)';
    addInterceptBtn.addEventListener('click', ()=>{
      if (!Array.isArray(modelObj.X)) modelObj.X = [];
      if (modelObj.X.includes('1')) {
        setStatus('Intercept already present.', 'info');
        return;
      }
      modelObj.X.unshift('1');
      rerenderModelX('Intercept added to Model.X', 'info');
    });
    xCard.appendChild(addInterceptBtn);

    wrapper.appendChild(xCard);

    const hrfCard = document.createElement('div');
    hrfCard.className = 'border rounded p-2 bg-white d-flex flex-column gap-2';
    const hrfHeader = document.createElement('div');
    hrfHeader.className = 'd-flex justify-content-between align-items-center';
    const hrfTitle = document.createElement('div');
    hrfTitle.className = 'small fw-bold';
    hrfTitle.textContent = 'HRF defaults (optional)';
    const hrfToggle = document.createElement('input');
    hrfToggle.type = 'checkbox';
    hrfToggle.className = 'form-check-input';
    hrfToggle.checked = Boolean(modelObj.HRF && typeof modelObj.HRF === 'object');
    hrfToggle.addEventListener('change', ()=>{
      if (hrfToggle.checked) {
        const previous = modelObj.HRF && typeof modelObj.HRF === 'object' ? modelObj.HRF : {};
        modelObj.HRF = {
          ...previous,
          Model: String(previous.Model || 'spm').trim() || 'spm',
          Variables: normalizeFriendlyHrfVariables()
        };
      } else {
        delete modelObj.HRF;
      }
      renderModelStructure();
      renderNodeModelFieldEditor(node, idx);
      setStatus('Node Model.HRF updated', 'info');
    });
    hrfHeader.appendChild(hrfTitle);
    hrfHeader.appendChild(hrfToggle);
    hrfCard.appendChild(hrfHeader);

    const hrfHint = document.createElement('div');
    hrfHint.className = 'small text-muted';
    hrfHint.textContent = 'Use the HRF on/off tag on each Design Matrix regressor to control HRF.Variables.';
    hrfCard.appendChild(hrfHint);

    if (modelObj.HRF && typeof modelObj.HRF === 'object') {
      const hrfModelRow = document.createElement('div');
      hrfModelRow.className = 'd-flex flex-column gap-1';
      const hrfModelLabel = document.createElement('label');
      hrfModelLabel.className = 'form-label small mb-0';
      hrfModelLabel.textContent = 'HRF.Model';
      const hrfModelInput = document.createElement('input');
      hrfModelInput.type = 'text';
      hrfModelInput.className = 'form-control form-control-sm';
      hrfModelInput.value = modelObj.HRF.Model || 'spm';
      hrfModelInput.addEventListener('change', ()=>{
        modelObj.HRF.Model = (hrfModelInput.value || '').trim() || 'spm';
        renderModelStructure();
        setStatus('Node Model.HRF.Model updated', 'info');
      });
      hrfModelRow.appendChild(hrfModelLabel);
      hrfModelRow.appendChild(hrfModelInput);
      hrfCard.appendChild(hrfModelRow);
    }

    wrapper.appendChild(hrfCard);

    const advanced = document.createElement('details');
    advanced.className = 'border rounded p-2';
    const advJsonSummary = document.createElement('summary');
    advJsonSummary.className = 'small fw-bold';
    advJsonSummary.textContent = 'Advanced JSON (Model only)';
    advanced.appendChild(advJsonSummary);

    const advHelp = document.createElement('div');
    advHelp.className = 'small text-muted mt-2';
    advHelp.textContent = 'Use this only for uncommon Model fields not covered above.';
    advanced.appendChild(advHelp);

    const advTa = document.createElement('textarea');
    advTa.className = 'form-control font-monospace mt-2';
    advTa.style.minHeight = '180px';
    advTa.value = JSON.stringify(modelObj, null, 2);
    advanced.appendChild(advTa);

    const advApply = document.createElement('button');
    advApply.type = 'button';
    advApply.className = 'btn btn-sm btn-outline-secondary mt-2';
    advApply.textContent = 'Apply Advanced JSON';
    advApply.addEventListener('click', ()=>{
      try {
        const parsed = JSON.parse(advTa.value);
        node.Model = parsed;
        ensureNodeModelObject(node, idx);
        renderModelStructure();
        renderNodeModelFieldEditor(node, idx);
        setStatus('Node Model updated from advanced JSON', 'info');
      } catch (e) {
        setStatus('Invalid JSON for Node.Model: ' + e.message, 'danger');
      }
    });
    advanced.appendChild(advApply);

    wrapper.appendChild(advanced);

    friendlyEditor.appendChild(wrapper);
  }

  function renderNodeJsonFieldEditor(node, field, idx){
    const wrapper = document.createElement('div');
    wrapper.className = 'd-flex flex-column gap-2';

    const currentValue = node[field];
    const defaultValue = defaultNodeFieldValue(field, idx);

    const help = document.createElement('div');
    help.className = 'small text-muted';
    help.textContent = `Edit Node.${field} as JSON.`;
    wrapper.appendChild(help);

    if (currentValue === undefined) {
      const initBtn = document.createElement('button');
      initBtn.type = 'button';
      initBtn.className = 'btn btn-sm btn-outline-secondary align-self-start';
      initBtn.textContent = `Initialize ${field}`;
      initBtn.addEventListener('click', ()=>{
        node[field] = cloneJson(defaultValue);
        renderModelStructure();
        selectNodeField(idx, field);
        setStatus(`${field} initialized`, 'info');
      });
      wrapper.appendChild(initBtn);
    }

    const ta = document.createElement('textarea');
    ta.className = 'form-control font-monospace';
    ta.style.minHeight = '260px';
    ta.value = JSON.stringify(currentValue === undefined ? defaultValue : currentValue, null, 2);
    ta.addEventListener('change', ()=>{
      try {
        node[field] = JSON.parse(ta.value);
        renderModelStructure();
        setStatus(`Node ${field} updated`, 'info');
      } catch (e) {
        setStatus(`Invalid JSON for ${field}`, 'danger');
      }
    });
    wrapper.appendChild(ta);

    friendlyEditor.appendChild(wrapper);
  }

  function selectNodeField(idx, field){
    currentNodeIndex = idx;
    currentSelection = { type: 'nodeField', idx, field };
    window.currentSelection = currentSelection;
    const node = Array.isArray(model?.Nodes) ? model.Nodes[idx] : null;
    if (!node) {
      currentSelection = { type: 'model' };
      window.currentSelection = currentSelection;
      setStatus('Node not found', 'danger');
      return;
    }

    const nodeLabel = `${node.Level || 'Run'} — ${node.Name || `node #${idx+1}`}`;
    selectedLabel.textContent = `${nodeLabel} — ${field}`;
    selectedMeta.textContent = `Node field editor`;
    if (editorMode === 'full') {
      if (typeof window.renderModelAccordionEditor === 'function') window.renderModelAccordionEditor();
      return;
    }
    friendlyEditor.innerHTML = '';

    if (field === 'Transformations') {
      renderTransformations(node);
      refreshRawEditorFromSelection();
      return;
    }

    if (field === 'Level') {
      const sel = document.createElement('select');
      sel.className = 'form-select';
      NODE_LEVEL_OPTIONS.forEach(level => {
        const opt = document.createElement('option');
        opt.value = level;
        opt.textContent = level;
        sel.appendChild(opt);
      });
      const rawLevel = node.Level ? String(node.Level) : 'Run';
      const normalizedLevel = NODE_LEVEL_OPTIONS.find(level => level.toLowerCase() === rawLevel.toLowerCase()) || 'Run';
      sel.value = normalizedLevel;
      sel.addEventListener('change', ()=>{
        node.Level = sel.value;
        renderModelStructure();
        renderNodeList();
        selectedLabel.textContent = `${node.Level || 'Run'} — ${node.Name || `node #${idx+1}`} — ${field}`;
        setStatus('Node Level updated', 'info');
      });
      friendlyEditor.appendChild(sel);
      refreshRawEditorFromSelection();
      return;
    }

    if (field === 'Name') {
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-control';
      input.value = node.Name || '';
      input.addEventListener('change', ()=>{
        node.Name = input.value;
        renderModelStructure();
        renderNodeList();
        selectedLabel.textContent = `${node.Level || 'Run'} — ${node.Name || `node #${idx+1}`} — ${field}`;
        setStatus('Node Name updated', 'info');
      });
      friendlyEditor.appendChild(input);
      refreshRawEditorFromSelection();
      return;
    }

    if (field === 'GroupBy') {
      if (!Array.isArray(node.GroupBy)) node.GroupBy = [];

      const wrapper = document.createElement('div');
      wrapper.className = 'd-flex flex-column gap-2';

      const help = document.createElement('div');
      help.className = 'small text-muted';
      help.textContent = 'Reserved options: run, session, subject, contrast. Additional metadata fields are also allowed.';
      wrapper.appendChild(help);

      const allOptions = Array.from(new Set([
        ...GROUPBY_RESERVED_OPTIONS,
        ...normalizeStringArray(window.modelEditorGroupByOptions),
        ...node.GroupBy
      ]));
      const select = document.createElement('select');
      select.className = 'form-select';
      select.multiple = true;
      select.size = Math.min(8, Math.max(4, allOptions.length));
      allOptions.forEach(optVal => {
        const opt = document.createElement('option');
        opt.value = optVal;
        opt.textContent = optVal;
        opt.selected = node.GroupBy.includes(optVal);
        select.appendChild(opt);
      });
      select.addEventListener('change', ()=>{
        node.GroupBy = Array.from(select.selectedOptions).map(o => o.value);
        renderModelStructure();
        setStatus('Node GroupBy updated', 'info');
      });
      wrapper.appendChild(select);

      const addRow = document.createElement('div');
      addRow.className = 'd-flex gap-2';
      const customInput = document.createElement('input');
      customInput.type = 'text';
      customInput.className = 'form-control';
      customInput.placeholder = 'Add custom GroupBy field';
      const addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'btn btn-outline-secondary';
      addBtn.textContent = 'Add';
      addBtn.addEventListener('click', ()=>{
        const value = customInput.value.trim();
        if (!value) return;
        if (!node.GroupBy.includes(value)) node.GroupBy.push(value);
        renderModelStructure();
        selectNodeField(idx, field);
        setStatus('Custom GroupBy field added', 'info');
      });
      addRow.appendChild(customInput);
      addRow.appendChild(addBtn);
      wrapper.appendChild(addRow);

      friendlyEditor.appendChild(wrapper);
      refreshRawEditorFromSelection();
      return;
    }

    if (field === 'Model') {
      renderNodeModelFieldEditor(node, idx);
      refreshRawEditorFromSelection();
      return;
    }

    if (['Contrasts', 'DummyContrasts'].includes(field)) {
      renderNodeJsonFieldEditor(node, field, idx);
      refreshRawEditorFromSelection();
      return;
    }

    renderNodeJsonFieldEditor(node, field, idx);
    refreshRawEditorFromSelection();
  }

  function selectNode(idx){
    selectNodeField(idx, 'Transformations');
  }

  function renderTransformations(node){
    friendlyEditor.innerHTML = '';
    refreshRawEditorFromSelection();
    const instr = Array.isArray(node.Transformations?.Instructions) ? node.Transformations.Instructions : [];
    if(!node.Transformations){
      const addBtn = document.createElement('button');
      addBtn.className = 'btn btn-sm btn-outline-success';
      addBtn.textContent = 'Add Transformations';
      addBtn.addEventListener('click', ()=>{
        node.Transformations = {Instructions:[]};
        renderTransformations(node);
      });
      friendlyEditor.appendChild(addBtn);
      return;
    }
    // Render instructions
    const list = document.createElement('div');
    list.className = 'd-flex flex-column gap-2';
    instr.forEach((instruction, i) => {
      const wrap = document.createElement('div');
      wrap.className = 'border rounded p-2 bg-white';
      const header = document.createElement('div');
      header.className = 'd-flex justify-content-between align-items-center mb-2';
      const nameInput = document.createElement('input');
      nameInput.type='text';
      nameInput.value = instruction.Name || '';
      nameInput.className='form-control form-control-sm';
      nameInput.addEventListener('change', ()=> {
        instruction.Name = nameInput.value;
      });
      header.appendChild(nameInput);

      const actions = document.createElement('div');
      actions.className='d-flex gap-2';
      const delBtn = document.createElement('button');
      delBtn.type='button';
      delBtn.className='btn btn-sm btn-outline-danger';
      delBtn.innerHTML = '<i class="fas fa-trash"></i>';
      delBtn.addEventListener('click', ()=> {
        node.Transformations.Instructions.splice(i,1);
        renderTransformations(node);
      });
      actions.appendChild(delBtn);
      header.appendChild(actions);
      wrap.appendChild(header);

      // For Replace instruction, show structured key/value editor for each replacement entry
      if (instruction.Name === 'Replace' && Array.isArray(instruction.Replace)) {
        const repWrap = document.createElement('div');

        function renderReplaceEntry(rep, j) {
          const entryCard = document.createElement('div');
          entryCard.className = 'border rounded p-2 mb-2 bg-light';

          const header = document.createElement('div');
          header.className = 'd-flex justify-content-between align-items-start mb-2';
          const title = document.createElement('div');
          title.className = 'small fw-bold';
          title.textContent = (rep && (rep.value || rep.name || rep.field)) ? (rep.value || rep.name || rep.field) : `Replace #${j+1}`;
          header.appendChild(title);
          const delBtn = document.createElement('button');
          delBtn.type = 'button';
          delBtn.className = 'btn btn-sm btn-outline-danger';
          delBtn.innerHTML = '<i class="fas fa-trash"></i>';
          delBtn.addEventListener('click', ()=>{ instruction.Replace.splice(j,1); renderTransformations(node); });
          header.appendChild(delBtn);
          entryCard.appendChild(header);

          const fields = document.createElement('div');
          fields.className = 'mb-2';

          // ensure rep is an object
          if (!rep || typeof rep !== 'object') instruction.Replace[j] = rep = {};

          function addFieldRow(key, value) {
            const row = document.createElement('div');
            row.className = 'mb-2';
            const label = document.createElement('label');
            label.className = 'form-label small mb-1';
            label.textContent = key;

            // primitive types get inline controls, arrays/objects get a textarea
            if (value === null || ['string','number','boolean'].includes(typeof value)) {
              const input = document.createElement('input');
              input.className = 'form-control form-control-sm';
              if (typeof value === 'boolean') {
                input.type = 'checkbox';
                input.checked = !!value;
              } else if (typeof value === 'number') {
                input.type = 'number';
                input.value = value;
              } else {
                input.type = 'text';
                input.value = value ?? '';
              }
              input.addEventListener('change', ()=>{
                if (input.type === 'checkbox') instruction.Replace[j][key] = input.checked;
                else if (input.type === 'number') instruction.Replace[j][key] = parseFloat(input.value);
                else instruction.Replace[j][key] = input.value;
                validateEntry();
              });
              row.appendChild(label);
              row.appendChild(input);
            } else {
              const ta = document.createElement('textarea');
              ta.className = 'form-control font-monospace';
              ta.style.minHeight = '72px';
              try{ ta.value = JSON.stringify(value, null, 2); }catch(e){ ta.value = String(value); }
              ta.addEventListener('change', ()=>{
                try{ instruction.Replace[j][key] = JSON.parse(ta.value); }catch(e){}
                validateEntry();
              });
              row.appendChild(label);
              row.appendChild(ta);
            }

            fields.appendChild(row);
          }

          // render existing keys
          Object.keys(rep).forEach(k => addFieldRow(k, rep[k]));

          // control to add new key
          const addKeyRow = document.createElement('div');
          addKeyRow.className = 'd-flex gap-2';
          const newKeyInput = document.createElement('input');
          newKeyInput.type = 'text';
          newKeyInput.className = 'form-control form-control-sm';
          newKeyInput.placeholder = 'new key (e.g. value, from, to)';
          const addKeyBtn = document.createElement('button');
          addKeyBtn.type = 'button';
          addKeyBtn.className = 'btn btn-sm btn-outline-secondary';
          addKeyBtn.textContent = 'Add Field';
          addKeyBtn.addEventListener('click', ()=>{
            const k = newKeyInput.value.trim(); if(!k) return; instruction.Replace[j][k] = '';
            renderTransformations(node);
          });
          addKeyRow.appendChild(newKeyInput); addKeyRow.appendChild(addKeyBtn);

          // validation indicator
          const validationDiv = document.createElement('div');
          validationDiv.className = 'small text-muted mt-1';
          function validateEntry(){
            const item = instruction.Replace[j];
            const hasValue = item && typeof item.value === 'string' && item.value.trim();
            if(!hasValue) validationDiv.innerHTML = '<span class="text-warning">Missing required field "value"</span>';
            else validationDiv.innerHTML = '<span class="text-success">OK</span>';
          }
          validateEntry();

          entryCard.appendChild(fields);
          entryCard.appendChild(addKeyRow);
          entryCard.appendChild(validationDiv);
          return entryCard;
        }

        instruction.Replace.forEach((rep, j) => {
          repWrap.appendChild(renderReplaceEntry(rep, j));
        });

        const addRep = document.createElement('button');
        addRep.type='button';
        addRep.className='btn btn-sm btn-outline-success';
        addRep.textContent='Add Replace Entry';
        addRep.addEventListener('click', ()=>{
          instruction.Replace.push({value: ''});
          renderTransformations(node);
        });
        repWrap.appendChild(addRep);
        wrap.appendChild(repWrap);
      } else {
        // Generic JSON editor for other instruction types
        const ta = document.createElement('textarea');
        ta.className='form-control font-monospace';
        ta.style.minHeight='120px';
        ta.value = JSON.stringify(instruction, null, 2);
        ta.addEventListener('change', ()=> {
          try{
            const parsed = JSON.parse(ta.value);
            node.Transformations.Instructions[i] = parsed;
          }catch(e){}
        });
        wrap.appendChild(ta);
      }

      list.appendChild(wrap);
    });

    // Controls to add instruction
    const controls = document.createElement('div');
    controls.className = 'd-flex gap-2 mt-2';
    const sel = document.createElement('select');
    sel.className='form-select form-select-sm';
    ['Replace','Rename','Filter','Custom'].forEach(v=>{
      const opt = document.createElement('option'); opt.value=v; opt.textContent=v; sel.appendChild(opt);
    });
    controls.appendChild(sel);
    const addInstrBtn = document.createElement('button');
    addInstrBtn.type='button';
    addInstrBtn.className='btn btn-sm btn-outline-success';
    addInstrBtn.textContent='Add Instruction';
    addInstrBtn.addEventListener('click', ()=>{
      const name = sel.value || 'Custom';
      const inst = name === 'Replace' ? {Name:'Replace', Replace: []} : {Name: name};
      node.Transformations.Instructions.push(inst);
      renderTransformations(node);
    });
    controls.appendChild(addInstrBtn);

    friendlyEditor.appendChild(list);
    friendlyEditor.appendChild(controls);
  }

  document.getElementById('btn-load-model').addEventListener('click', ()=>{
    const path = document.getElementById('model-path-input').value.trim();
    if(!path) { setStatus('Enter model path first', 'warning'); return; }
    modelPath = path;
    fetchModel(modelPath);
  });

  const bidsInputEl = document.getElementById('input-BIDS_DIR');
  if (bidsInputEl) {
    bidsInputEl.addEventListener('change', async ()=> {
      await refreshInputEntityOptions(true);
      await refreshModelEditorHintData(model);
      rerenderCurrentSelection();
      if (typeof window.renderModelAccordionEditor === 'function' && editorMode === 'full') {
        window.renderModelAccordionEditor();
      }
    });
  }

  const browseBidsBtn = document.getElementById('btn-browse-bids');
  if (browseBidsBtn) {
    browseBidsBtn.addEventListener('click', async ()=> {
      const current = bidsInputEl ? bidsInputEl.value : '';
      const entered = window.prompt('Enter BIDS folder path', current || '');
      if (entered === null) return;
      if (bidsInputEl) bidsInputEl.value = entered.trim();
      await refreshInputEntityOptions(true);
      await refreshModelEditorHintData(model);
      rerenderCurrentSelection();
      if (typeof window.renderModelAccordionEditor === 'function' && editorMode === 'full') {
        window.renderModelAccordionEditor();
      }
    });
  }

  const prepInputEl = document.getElementById('input-FMRIPREP_DIR');
  if (prepInputEl) {
    prepInputEl.addEventListener('change', async ()=> {
      await refreshSpaceInputOptions(true);
      await refreshModelEditorHintData(model);
      if (selectedLabel && selectedLabel.textContent === 'Model — Input') renderInputFieldEditor();
      rerenderCurrentSelection();
      if (typeof window.renderModelAccordionEditor === 'function' && editorMode === 'full') {
        window.renderModelAccordionEditor();
      }
    });
  }

  const browsePrepBtn = document.getElementById('btn-browse-fmriprep');
  if (browsePrepBtn) {
    browsePrepBtn.addEventListener('click', async ()=> {
      const current = prepInputEl ? prepInputEl.value : '';
      const entered = window.prompt('Enter fMRIPrep folder path', current || '');
      if (entered === null) return;
      if (prepInputEl) prepInputEl.value = entered.trim();
      await refreshSpaceInputOptions(true);
      await refreshModelEditorHintData(model);
      if (selectedLabel && selectedLabel.textContent === 'Model — Input') renderInputFieldEditor();
      rerenderCurrentSelection();
      if (typeof window.renderModelAccordionEditor === 'function' && editorMode === 'full') {
        window.renderModelAccordionEditor();
      }
    });
  }

  document.getElementById('btn-toggle-raw').addEventListener('click', async ()=>{
    const shell = document.getElementById('model-editor-shell');
    const trans = document.getElementById('transformations-editor');
    if (!model) {
      setStatus('Load a model before opening JSON view.', 'warning');
      return;
    }

    if (!rawMode) {
      rawModeReturnEditor = editorMode;
      if (editorMode === 'full' && shell && trans) {
        editorMode = 'friendly';
        shell.style.display = 'none';
        trans.style.display = 'block';
        const fullBtn = document.getElementById('btn-open-full-editor');
        if (fullBtn) fullBtn.textContent = 'Workflow View';
      }
      setRawMode(true);
      refreshRawEditorFromSelection();
      setStatus(`JSON editor opened for ${getCurrentSelectionLabel()}.`, 'info');
      return;
    }

    const selectionLabel = getCurrentSelectionLabel();
    try {
      const parsed = JSON.parse(rawEditor.value);
      applyRawValueToSelection(parsed);
      modelEditorDraft = model;
      await refreshModelEditorHintData(model);
      renderNodeList();
      renderModelStructure();
      setRawMode(false);
      if (rawModeReturnEditor === 'full' && shell && trans) {
        editorMode = 'full';
        trans.style.display = 'none';
        shell.style.display = 'block';
        const fullBtn = document.getElementById('btn-open-full-editor');
        if (fullBtn) fullBtn.textContent = 'Field View';
        if (typeof window.renderModelAccordionEditor === 'function') window.renderModelAccordionEditor();
      } else {
        rerenderCurrentSelection();
        refreshSpaceInputOptions(false).then(() => {
          if (selectedLabel && selectedLabel.textContent === 'Model — Input') renderInputFieldEditor();
        });
      }
      setStatus(`JSON updated for ${selectionLabel}.`, 'success');
    } catch (e) {
      setStatus('Invalid JSON in raw editor: ' + e.message, 'danger');
    }
  });

  document.getElementById('btn-save-model').addEventListener('click', async ()=>{
    if(!modelPath) { setStatus('No model path set', 'warning'); return; }
    if(editorMode === 'friendly'){
      setStatus('Saving...', 'info');
      try{
        const resp = await fetch('/file_content', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({path: modelPath, content: JSON.stringify(model, null, 2), validate_json:true})
        });
        const result = await resp.json();
        if(result.success){
          setStatus('Model saved.', 'success');
        } else {
          setStatus('Save failed: ' + (result.error || 'unknown'), 'danger');
        }
      }catch(e){
        setStatus('Save exception: ' + e.message, 'danger');
      }
    } else {
      // full editor save (function defined in full-editor script block)
      if (typeof saveModelEditor === 'function') await saveModelEditor();
    }
  });

  // Toggle between workflow editor and per-field editor
  document.getElementById('btn-open-full-editor').addEventListener('click', ()=>{
    const shell = document.getElementById('model-editor-shell');
    const trans = document.getElementById('transformations-editor');
    const btn = document.getElementById('btn-open-full-editor');
    if(!shell || !trans) return;
    if (editorMode === 'full') {
      // Switch to per-field view
      editorMode = 'friendly';
      setRawMode(false);
      trans.style.display = 'block';
      shell.style.display = 'none';
      if (btn) btn.textContent = 'Workflow View';
      rerenderCurrentSelection();
    } else {
      // Switch to workflow editor
      editorMode = 'full';
      setRawMode(false);
      trans.style.display = 'none';
      shell.style.display = 'block';
      if (btn) btn.textContent = 'Field View';
      if (typeof window.renderModelAccordionEditor === 'function') window.renderModelAccordionEditor();
    }
  });

  // Double-click header label: switch to friendly per-field editor
  document.getElementById('selected-node-label').addEventListener('dblclick', ()=>{
    const shell = document.getElementById('model-editor-shell');
    const trans = document.getElementById('transformations-editor');
    const btn = document.getElementById('btn-open-full-editor');
    if(!shell || !trans) return;
    editorMode = 'friendly';
    shell.style.display = 'none';
    trans.style.display = 'block';
    if (btn) btn.textContent = 'Workflow View';
    rerenderCurrentSelection();
  });

  // Auto-load if model_path provided from server-side
  const initialPath = "";
  if(initialPath){
    document.getElementById('model-path-input').value = initialPath;
    modelPath = initialPath;
    fetchModel(modelPath);
  } else if (modelPath){
    fetchModel(modelPath);
  } else {
    refreshInputEntityOptions(false);
  }
})();
