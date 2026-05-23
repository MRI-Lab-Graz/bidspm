
/* Full model editor functions (adapted from analysis page) */
(function(){
  const NUISANCE_REGRESSOR_RX = /^(framewise_displacement|trans_[xyz]|rot_[xyz]|a_comp_cor|dvars|std_dvars|non_steady_state_outlier|cosine\d*|white_matter|csf|global_signal)/;
  const REQUIRED_ROOT_KEYS = ['Name', 'BIDSModelVersion', 'Input', 'Nodes'];
  const previewValidationState = window.__modelPreviewValidationState && typeof window.__modelPreviewValidationState === 'object'
    ? window.__modelPreviewValidationState
    : { timer: null, runId: 0 };
  window.__modelPreviewValidationState = previewValidationState;
  const READONLY_MODEL_PATHS = [
    /^BIDSModelVersion$/,
    /^Input\.task$/,
    /^Input\.task\[\d+\]$/,
    /^Nodes\[\d+\]\.Level$/,
    /^Nodes\[\d+\]\.Name$/
  ];

  function isReadonlyModelPath(path) { return READONLY_MODEL_PATHS.some(rx => rx.test(path)); }

  function appendModelMetaPill(container, text, tone = 'neutral'){
    const pill = document.createElement('span'); pill.className = `model-meta-pill model-meta-pill-${tone}`; pill.textContent = text; container.appendChild(pill);
  }

  function pathTokens(path) {
    const tokens = [];
    const rx = /([^.[\]]+)|\[(\d+)\]/g; let m;
    while ((m = rx.exec(path)) !== null) { if (m[1] !== undefined) tokens.push(m[1]); else tokens.push(Number(m[2])); }
    return tokens;
  }

  function getByPath(root, path) { return pathTokens(path).reduce((acc, tk) => (acc == null ? acc : acc[tk]), root); }
  function setByPath(root, path, value) {
    const tokens = pathTokens(path); if (!tokens.length) return; let cursor = root; for (let i = 0; i < tokens.length - 1; i++) { cursor = cursor[tokens[i]]; if (cursor == null) return; } cursor[tokens[tokens.length - 1]] = value;
  }

  function parsePrimitiveInput(raw, original) {
    if (typeof original === 'number') { const parsed = Number(raw); return Number.isNaN(parsed) ? original : parsed; }
    if (typeof original === 'boolean') return raw === true || raw === 'true';
    if (original === null) return raw === '' ? null : raw;
    return String(raw);
  }

  function isNuisanceRegressor(value) { if (typeof value !== 'string') return false; return NUISANCE_REGRESSOR_RX.test(value.trim()); }

  function defaultArrayItemForPath(path) {
    if (path === 'Nodes') return { Level: 'Run', Name: 'subject_level', GroupBy: ['run','subject'], Model: { X: ['trial_type'], HRF: { Variables: ['trial_type'], Model: 'spm' }, Type: 'glm' }, Contrasts: [] };
    if (path === 'Edges') return getEdgeDefaultValue();
    if (/\.Contrasts$/.test(path)) return { Name: `Contrast_${Date.now().toString().slice(-4)}`, ConditionList: ['trial_type.active','trial_type.control'], Weights: [1,-1], Test: 't' };
    if (/\.ConditionList$/.test(path)) return 'trial_type.active';
    if (/\.Weights$/.test(path)) return 0;
    if (/\.X$/.test(path)) return modelEditorInterestRegressors[0] || 'trial_type';
    if (/\.GroupBy$/.test(path)) return 'run';
    if (/\.Variables$/.test(path)) return 'trial_type';
    return '';
  }
  function addArrayItem(path){ const arr = getByPath(modelEditorDraft, path); if (!Array.isArray(arr)) return; arr.push(defaultArrayItemForPath(path)); }
  function moveArrayItem(path, direction){ const match = path.match(/^(.*)\[(\d+)\]$/); if (!match) return; const arrayPath = match[1]; const index = Number(match[2]); const arr = getByPath(modelEditorDraft, arrayPath); if (!Array.isArray(arr)) return; const targetIndex = direction === 'up' ? index-1 : index+1; if (targetIndex<0||targetIndex>=arr.length) return; [arr[index], arr[targetIndex]] = [arr[targetIndex], arr[index]]; }
  function removeArrayItem(path){ const match = path.match(/^(.*)\[(\d+)\]$/); if (!match) return; const arrayPath = match[1]; const index = Number(match[2]); const arr = getByPath(modelEditorDraft, arrayPath); if (!Array.isArray(arr)) return; if (index<0||index>=arr.length) return; arr.splice(index,1); }
  function isModelXPath(path){ return /\.Model\.X\[\d+\]$/.test(path); }
  function isDuplicateModelXRegressor(path, candidate){ const match = path.match(/^(.*)\[(\d+)\]$/); if (!match) return false; const arrayPath = match[1]; const index = Number(match[2]); const arr = getByPath(modelEditorDraft, arrayPath); if (!Array.isArray(arr)) return false; const normalized = String(candidate||'').trim(); return arr.some((val,i) => i!==index && String(val||'').trim()===normalized); }
  function hasConfoundColumn(columns, confoundName){ const normalized = String(confoundName || '').trim(); if (!normalized) return false; return (Array.isArray(columns) ? columns : []).some(col => { const candidate = String(col || '').trim(); return candidate === normalized || candidate.startsWith(`${normalized}_`); }); }
  function setModelEditorStatus(message = '', tone = 'info'){ const status = document.getElementById('model-editor-status'); if (!status) return; if (!message) { status.innerHTML = ''; return; } status.innerHTML = `<div class="alert alert-${tone} py-1 x-small mb-2">${message}</div>`; }
  function moveRegressorToIndex(arrayPath, fromIndex, toIndex){ const arr = getByPath(modelEditorDraft, arrayPath); if (!Array.isArray(arr)) return; if (fromIndex === toIndex) return; if (fromIndex < 0 || fromIndex >= arr.length) return; if (toIndex < 0 || toIndex > arr.length) return; const [moved] = arr.splice(fromIndex, 1); let targetIndex = toIndex; if (fromIndex < toIndex) targetIndex -= 1; arr.splice(targetIndex, 0, moved); setModelEditorStatus('Regressor order updated', 'info'); renderModelAccordionEditor(); }
  function addRegressorToModelX(arrayPath, regressor, insertIndex = null){ const arr = getByPath(modelEditorDraft, arrayPath); if (!Array.isArray(arr)) return; const normalized = String(regressor||'').trim(); if(!normalized) return; if (arr.some(v=>String(v||'').trim()===normalized)){ setModelEditorStatus(`Regressor already selected: ${normalized}`, 'warning'); return; } if (insertIndex === null || insertIndex === undefined || insertIndex < 0 || insertIndex > arr.length) arr.push(normalized); else arr.splice(insertIndex, 0, normalized); setModelEditorStatus('', 'info'); renderModelAccordionEditor(); }

  function createPrimitiveRow(container, label, value, path, locked = false, depth = 0) {
    const row = document.createElement('div'); row.className = `json-row d-flex align-items-center gap-2 json-row-depth-${Math.min(depth,4)}`;
    const keyEl = document.createElement('span'); keyEl.className='json-key fw-semibold'; keyEl.textContent = label; row.appendChild(keyEl);
    const inputWrap = document.createElement('div'); inputWrap.className='json-inline-value';
    const pathEl = document.createElement('div'); pathEl.className='json-path mb-1'; pathEl.textContent = path; pathEl.style.display = showModelTechnicalPaths ? 'block' : 'none'; inputWrap.appendChild(pathEl);
    const isModelXEntry = isModelXPath(path); const isGroupByEntry = /\.GroupBy\[\d+\]$/.test(path); const useInterestDropdown = isModelXEntry && typeof value === 'string' && !isNuisanceRegressor(value) && modelEditorInterestRegressors.length>0;
    let input;
    if (isGroupByEntry) { input = document.createElement('select'); input.className='form-select form-select-sm'; const options = Array.from(new Set([...(modelEditorGroupByOptions||[]), value])); options.forEach(optVal=>{ const opt = document.createElement('option'); opt.value=optVal; opt.textContent=optVal; input.appendChild(opt); }); input.value = String(value); }
    else if (useInterestDropdown) { input = document.createElement('select'); input.className='form-select form-select-sm'; const options = Array.from(new Set([value, ...modelEditorInterestRegressors])); options.forEach(optVal=>{ const opt=document.createElement('option'); opt.value=optVal; opt.textContent=optVal; input.appendChild(opt); }); input.value=value; }
    else if (typeof value === 'boolean') { input = document.createElement('select'); input.className='form-select form-select-sm'; input.innerHTML = '<option value="true">true</option><option value="false">false</option>'; input.value = value ? 'true' : 'false'; }
    else if (typeof value === 'number') { input = document.createElement('input'); input.type='number'; input.step='any'; input.className='form-control form-control-sm font-monospace'; input.value = String(value); }
    else { input = document.createElement('input'); input.type='text'; input.className='form-control form-control-sm font-monospace'; input.value = value===null ? '' : String(value); }
    if (locked) { input.readOnly = true; input.disabled = true; input.classList.add('json-locked'); input.title = 'Locked mandatory field'; }
    else { input.addEventListener('change', (e)=>{ const current = getByPath(modelEditorDraft, path); const newValue = parsePrimitiveInput(e.target.value, current); if (isModelXEntry && isDuplicateModelXRegressor(path, newValue)){ const status = document.getElementById('model-editor-status'); status.innerHTML = `<div class="alert alert-warning py-1 x-small mb-2">Regressor already selected: ${newValue}</div>`; e.target.value = current; return; } setByPath(modelEditorDraft, path, newValue); updateModelJsonPreview(); }); }
    inputWrap.appendChild(input); row.appendChild(inputWrap);
    if (locked) { const badge = document.createElement('span'); badge.className='badge text-bg-light border'; badge.textContent='Locked'; row.appendChild(badge); }
    else if (isModelXEntry && isNuisanceRegressor(value)) { const badge = document.createElement('span'); badge.className='badge text-bg-secondary'; badge.textContent='Nuisance'; row.appendChild(badge); }
    else if (useInterestDropdown) { const badge = document.createElement('span'); badge.className='badge text-bg-success'; badge.textContent='Interest'; row.appendChild(badge); }
    if (isModelXEntry && !locked) { const match = path.match(/^(.*)\[(\d+)\]$/); if (match) { const arrayPath = match[1]; const index = Number(match[2]); const arr = getByPath(modelEditorDraft, arrayPath) || []; const actions = document.createElement('div'); actions.className='json-row-actions'; const upBtn = document.createElement('button'); upBtn.type='button'; upBtn.className='btn btn-sm btn-outline-secondary'; upBtn.title='Move up'; upBtn.innerHTML='<i class="fas fa-arrow-up"></i>'; upBtn.disabled = index===0; upBtn.addEventListener('click', ()=>{ moveArrayItem(path,'up'); renderModelAccordionEditor(); }); const downBtn = document.createElement('button'); downBtn.type='button'; downBtn.className='btn btn-sm btn-outline-secondary'; downBtn.title='Move down'; downBtn.innerHTML='<i class="fas fa-arrow-down"></i>'; downBtn.disabled = index===arr.length-1; downBtn.addEventListener('click', ()=>{ moveArrayItem(path,'down'); renderModelAccordionEditor(); }); const delBtn = document.createElement('button'); delBtn.type='button'; delBtn.className='btn btn-sm btn-outline-danger'; delBtn.title='Remove regressor'; delBtn.innerHTML='<i class="fas fa-times"></i>'; delBtn.addEventListener('click', ()=>{ removeArrayItem(path); renderModelAccordionEditor(); }); actions.appendChild(upBtn); actions.appendChild(downBtn); actions.appendChild(delBtn); row.appendChild(actions); } }
    if (isGroupByEntry && !locked) { const actions = document.createElement('div'); actions.className='json-row-actions'; const removeBtn = document.createElement('button'); removeBtn.type='button'; removeBtn.className='btn btn-sm btn-outline-danger'; removeBtn.title='Remove'; removeBtn.innerHTML='<i class="fas fa-trash"></i>'; removeBtn.addEventListener('click', ()=>{ removeArrayItem(path); renderModelAccordionEditor(); }); actions.appendChild(removeBtn); row.appendChild(actions); }
    if (!isModelXEntry && !isGroupByEntry && !locked && /\[\d+\]$/.test(path)) { const actions = document.createElement('div'); actions.className='json-row-actions'; const delBtn = document.createElement('button'); delBtn.type='button'; delBtn.className='btn btn-sm btn-outline-danger'; delBtn.title='Remove'; delBtn.innerHTML='<i class="fas fa-times"></i>'; delBtn.addEventListener('click', ()=>{ removeArrayItem(path); renderModelAccordionEditor(); }); actions.appendChild(delBtn); row.appendChild(actions); }
    container.appendChild(row);
  }

  function createBranchAccordion(container, label, childPath, childValue, inheritedLocked, depth = 0) {
    const item = document.createElement('div'); item.className = `accordion-item border-0 mb-2 json-depth-${Math.min(depth,4)}`;
    const idBase = `json-${childPath.replace(/[^a-zA-Z0-9]/g,'-')}`; const headerId = `${idBase}-h`; const collapseId = `${idBase}-c`;
    const h2 = document.createElement('h2'); h2.className='accordion-header'; h2.id = headerId; const headerWrap = document.createElement('div'); headerWrap.className='d-flex align-items-center gap-2'; const btn = document.createElement('button'); btn.className='accordion-button py-2 flex-grow-1'; btn.type='button'; btn.setAttribute('data-bs-toggle','collapse'); btn.setAttribute('data-bs-target', `#${collapseId}`); btn.setAttribute('aria-expanded','false'); btn.setAttribute('aria-controls', collapseId); const count = Array.isArray(childValue) ? childValue.length : Object.keys(childValue||{}).length; let displayLabel = label; if (/^Nodes\[\d+\]$/.test(childPath) && childValue && typeof childValue === 'object'){ const lvl = childValue.Level || 'Run'; const nm = childValue.Name || 'node'; displayLabel = `${lvl} - ${nm}`; } const heading = document.createElement('span'); heading.className='model-branch-heading'; const labelEl = document.createElement('span'); labelEl.className='model-branch-label'; labelEl.textContent = displayLabel; heading.appendChild(labelEl); if (showModelTechnicalPaths) { const pathEl = document.createElement('span'); pathEl.className='model-branch-path'; pathEl.textContent = childPath; heading.appendChild(pathEl); } const meta = document.createElement('span'); meta.className='model-branch-meta'; getBranchBadgeDescriptors(childPath, childValue).forEach(b => appendModelMetaPill(meta, b.text, b.tone)); if (!meta.childNodes.length) appendModelMetaPill(meta, `${count} ${Array.isArray(childValue) ? 'items' : 'fields'}`, 'neutral'); btn.appendChild(heading); btn.appendChild(meta); headerWrap.appendChild(btn);
    const isModelXArray = /\.Model\.X$/.test(childPath); const isGroupByArray = /\.GroupBy$/.test(childPath);
    if (Array.isArray(childValue) && !inheritedLocked && !isModelXArray && !isGroupByArray){ const addBtn = document.createElement('button'); addBtn.type='button'; addBtn.className='btn btn-sm btn-outline-success json-add-btn'; addBtn.textContent = '+ Add'; addBtn.addEventListener('click', (e)=>{ e.preventDefault(); e.stopPropagation(); addArrayItem(childPath); renderModelAccordionEditor(); }); headerWrap.appendChild(addBtn); }
    if (!inheritedLocked && /\[\d+\]$/.test(childPath)){ const delBtn = document.createElement('button'); delBtn.type='button'; delBtn.className='btn btn-sm btn-outline-danger json-add-btn'; delBtn.title='Delete'; delBtn.innerHTML='<i class="fas fa-times"></i>'; delBtn.addEventListener('click', (e)=>{ e.preventDefault(); e.stopPropagation(); removeArrayItem(childPath); renderModelAccordionEditor(); }); headerWrap.appendChild(delBtn); }
    h2.appendChild(headerWrap);
    const collapse = document.createElement('div'); collapse.id = collapseId; collapse.dataset.jsonPath = childPath; const wasOpen = modelEditorOpenPaths.has(childPath) || (!modelEditorOpenPaths.size && depth <= 1); collapse.className = `accordion-collapse collapse ${wasOpen ? 'show' : ''}`; btn.className = `accordion-button ${wasOpen ? '' : 'collapsed'} py-2 flex-grow-1`; btn.setAttribute('aria-expanded', wasOpen ? 'true' : 'false'); collapse.setAttribute('aria-labelledby', headerId);
    const body = document.createElement('div'); body.className='accordion-body py-2'; renderJsonEditor(body, childValue, childPath, inheritedLocked, depth+1); collapse.appendChild(body);
    item.appendChild(h2); item.appendChild(collapse); container.appendChild(item);
  }

  function getBranchBadgeDescriptors(path, value) {
    if (/^Nodes\[\d+\]$/.test(path) && value && typeof value === 'object'){
      const readyChecks = [ Boolean(value.Level), Boolean(value.Name), Array.isArray(value.GroupBy) && value.GroupBy.length>0, Boolean(value.Model?.Type), Array.isArray(value.Model?.X) && value.Model.X.length>0 ];
      return [ { text: `Ready ${readyChecks.filter(Boolean).length}/5`, tone: getModelPillTone(readyChecks.filter(Boolean).length, readyChecks.length) }, { text: `Contrasts ${Array.isArray(value.Contrasts) ? value.Contrasts.length : 0}`, tone: 'neutral' } ];
    }
    if (/\.Model$/.test(path) && value && typeof value === 'object'){
      const regressorCount = Array.isArray(value.X) ? value.X.length : 0; return [ { text: value.Type ? `Type ${value.Type}` : 'Type unset', tone: value.Type ? 'success' : 'neutral' }, { text: `Regressors ${regressorCount}`, tone: regressorCount>0 ? 'success' : 'neutral' } ];
    }
    if (/\.Contrasts$/.test(path) && Array.isArray(value)) return [{ text: `${value.length} contrast${value.length===1?'':'s'}`, tone: value.length>0 ? 'success' : 'neutral' }];
    if (/\.GroupBy$/.test(path) && Array.isArray(value)) return [{ text: `${value.length} grouping entr${value.length===1?'y':'ies'}`, tone: value.length>0 ? 'success' : 'neutral' }];
    if (/\.ConditionList$/.test(path) && Array.isArray(value)) return [{ text: `${value.length} condition${value.length===1?'':'s'}`, tone: value.length>0 ? 'success' : 'neutral' }];
    if (Array.isArray(value)) return [{ text: `${value.length} item${value.length===1?'':'s'}`, tone: value.length>0 ? 'neutral' : 'neutral' }];
    if (value && typeof value === 'object'){ const stats = getDirectFieldCompletion(value); return [{ text: `Fields ${stats.filled}/${stats.total}`, tone: getModelPillTone(stats.filled, stats.total) }]; }
    return [];
  }

  function getDirectFieldCompletion(value) { if (Array.isArray(value)) return { total: 1, filled: value.length>0 ? 1:0 }; if (value && typeof value === 'object'){ const entries = Object.entries(value); if (!entries.length) return { total:1, filled:0 }; return { total: entries.length, filled: entries.filter(([,child])=> isFilledModelValue(child)).length }; } return { total:1, filled: isFilledModelValue(value) ? 1 : 0 }; }
  function isFilledModelValue(value){ if (Array.isArray(value)) return value.some(item=> isFilledModelValue(item)); if (value && typeof value === 'object') return Object.values(value).some(item => isFilledModelValue(item)); if (typeof value === 'string') return value.trim() !== ''; return value !== null && value !== undefined; }
  function getModelPillTone(filled, total){ if (!total || filled<=0) return 'neutral'; const pct = Math.round((filled/total)*100); if (pct>=100) return 'success'; if (pct>=45) return 'warning'; return 'neutral'; }

  function getCompletionDotClass(filled, total){
    const tone = getModelPillTone(filled, total);
    if (tone === 'success') return 'dot-success';
    if (tone === 'warning') return 'dot-warning';
    return 'dot-neutral';
  }

  function formatModelSectionLabel(key){
    return String(key || '')
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\b\w/g, c => c.toUpperCase());
  }

  function getGenericSectionStats(value, key){
    const stats = getDirectFieldCompletion(value);
    return {
      filled: stats.filled,
      total: stats.total,
      subtitle: `Additional section: ${formatModelSectionLabel(key)}`,
      badges: [
        { text: `Fields ${stats.filled}/${stats.total}`, tone: getModelPillTone(stats.filled, stats.total) }
      ],
      dotClass: getCompletionDotClass(stats.filled, stats.total)
    };
  }

  function createInlineNote(text){
    const note = document.createElement('div');
    note.className = 'small text-muted';
    note.textContent = text;
    return note;
  }

  function getSelectedModelTasks(){
    return normalizeEditorStringArray(modelEditorDraft?.Input?.task);
  }

  function parseCsvValues(raw){
    return String(raw || '')
      .split(',')
      .map(v => v.trim())
      .filter(Boolean);
  }

  function createModelTaskPicker(){
    if (!modelEditorDraft || typeof modelEditorDraft !== 'object') {
      return createInlineNote('No model loaded.');
    }

    if (!modelEditorDraft.Input || typeof modelEditorDraft.Input !== 'object') {
      modelEditorDraft.Input = {};
    }
    if (!Array.isArray(modelEditorDraft.Input.task)) {
      modelEditorDraft.Input.task = [];
    }

    const wrap = document.createElement('div');
    wrap.className = 'border rounded p-2 mb-2 bg-white d-flex flex-column gap-2';

    const title = document.createElement('div');
    title.className = 'small fw-bold';
    title.textContent = 'Input.task (required)';
    wrap.appendChild(title);

    const sharedInputEntityValues = (window.modelEditorInputEntityValues && typeof window.modelEditorInputEntityValues === 'object')
      ? window.modelEditorInputEntityValues
      : {};
    const sharedBidsTasks = Array.isArray(window.modelEditorBidsTasks)
      ? window.modelEditorBidsTasks
      : [];
    const datasetTasks = Array.from(new Set([
      ...normalizeEditorStringArray(sharedInputEntityValues.task),
      ...normalizeEditorStringArray(sharedBidsTasks)
    ]));
    const currentTasks = getSelectedModelTasks();
    const allTasks = Array.from(new Set([...datasetTasks, ...currentTasks]));

    async function applySelectedTask(task) {
      modelEditorDraft.Input.task = task ? [String(task).trim()] : [];
      if (typeof window.refreshSpaceInputOptions === 'function') {
        await window.refreshSpaceInputOptions(false);
      }
      if (typeof window.refreshModelEditorHintData === 'function') {
        await window.refreshModelEditorHintData(modelEditorDraft);
      }
      renderModelAccordionEditor();
      setModelEditorStatus(modelEditorDraft.Input.task.length
        ? `Input.task set to ${modelEditorDraft.Input.task[0]}.`
        : 'Input.task cleared.', modelEditorDraft.Input.task.length ? 'info' : 'warning');
    }

    const hint = document.createElement('div');
    hint.className = 'small text-muted';
    hint.textContent = datasetTasks.length
      ? 'Choose one task from the detected BIDS func files. Task-derived trial types are filtered to this selection.'
      : 'No tasks were detected automatically. Enter a single task label manually.';
    wrap.appendChild(hint);

    const actions = document.createElement('div');
    actions.className = 'd-flex gap-2 flex-wrap';

    if (allTasks.length) {
      const select = document.createElement('select');
      select.className = 'form-select form-select-sm';
      const currentValue = currentTasks.length === 1 ? currentTasks[0] : '';
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = currentTasks.length > 1
        ? `Multiple tasks selected in JSON (${currentTasks.join(', ')})`
        : 'Select a task';
      select.appendChild(placeholder);
      allTasks.forEach(task => {
        const option = document.createElement('option');
        option.value = task;
        option.textContent = datasetTasks.includes(task) ? task : `${task} (from model)`;
        select.appendChild(option);
      });
      select.value = currentValue;
      select.addEventListener('change', async ()=>{
        await applySelectedTask(select.value);
      });
      wrap.appendChild(select);

      const clearBtn = document.createElement('button');
      clearBtn.type = 'button';
      clearBtn.className = 'btn btn-sm btn-outline-secondary';
      clearBtn.textContent = 'Clear';
      clearBtn.addEventListener('click', async ()=>{
        select.value = '';
        await applySelectedTask('');
      });
      actions.appendChild(clearBtn);

      if (currentTasks.length > 1) {
        const warn = document.createElement('div');
        warn.className = 'small text-warning';
        warn.textContent = 'Multiple tasks are currently stored in the model. Task-specific previews are hidden until you choose a single task here.';
        wrap.appendChild(warn);
      }
    } else {
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-control form-control-sm';
      input.placeholder = 'e.g. motor';
      input.value = currentTasks[0] || '';
      wrap.appendChild(input);

      const applyBtn = document.createElement('button');
      applyBtn.type = 'button';
      applyBtn.className = 'btn btn-sm btn-outline-secondary';
      applyBtn.textContent = 'Apply';
      applyBtn.addEventListener('click', async ()=>{
        await applySelectedTask(input.value.trim());
      });

      const clearBtn = document.createElement('button');
      clearBtn.type = 'button';
      clearBtn.className = 'btn btn-sm btn-outline-secondary';
      clearBtn.textContent = 'Clear';
      clearBtn.addEventListener('click', async ()=>{
        input.value = '';
        await applySelectedTask('');
      });

      actions.appendChild(applyBtn);
      actions.appendChild(clearBtn);
    }

    wrap.appendChild(actions);

    return wrap;
  }

  function getModelEditorSections(model) {
    const sections = [
      { id:'__section_overview', label:'Model Overview', path:'', statePath:'__section_overview', value: getOverviewSectionValue(model), kind:'overview', icon:'fa-file-lines', stats: getOverviewSectionStats(model) },
      { id:'Input', label:'Input', path:'Input', statePath:'Input', value: model?.Input ?? {}, kind:'input', icon:'fa-sliders', stats: getInputSectionStats(model?.Input) },
      { id:'Nodes', label:'Nodes', path:'Nodes', statePath:'Nodes', value: Array.isArray(model?.Nodes) ? model.Nodes : [], kind:'nodes', icon:'fa-diagram-project', stats: getNodesSectionStats(model?.Nodes) },
      { id:'Edges', label:'Edges', path:'Edges', statePath:'Edges', value: Array.isArray(model?.Edges) ? model.Edges : [], kind:'edges', icon:'fa-share-nodes', stats: getEdgesSectionStats(model?.Edges) }
    ];

    Object.entries(model || {}).forEach(([key, value]) => {
      if (key === 'Input' || key === 'Nodes' || key === 'Edges' || value === null || typeof value !== 'object') {
        return;
      }
      sections.push({
        id: key,
        label: formatModelSectionLabel(key),
        path: key,
        statePath: key,
        value,
        kind: Array.isArray(value) ? 'array' : 'object',
        icon: Array.isArray(value) ? 'fa-layer-group' : 'fa-folder-tree',
        stats: getGenericSectionStats(value, key)
      });
    });

    return sections;
  }

  function getOverviewSectionValue(model) { const primitiveKeys = Object.entries(model || {}).filter(([key,value]) => key!=='Input' && key!=='Nodes' && (value===null || typeof value !== 'object')).map(([key])=>key); const keys = Array.from(new Set(['Name','BIDSModelVersion','Description', ...primitiveKeys])); return Object.fromEntries(keys.map(key => [key, model?.[key] ?? ''])); }
  function getOverviewSectionStats(model) { const overviewValue = getOverviewSectionValue(model); const keys = Object.keys(overviewValue); const filled = keys.filter(key => isFilledModelValue(overviewValue[key])).length; const requiredKeys = ['Name','BIDSModelVersion']; const requiredFilled = requiredKeys.filter(key => isFilledModelValue(model?.[key])).length; return { filled, total: keys.length, subtitle:'Name, version and metadata', badges:[ { text: `Required ${requiredFilled}/${requiredKeys.length}`, tone: requiredFilled===requiredKeys.length ? 'success' : 'warning' }, { text: `Fields ${filled}/${keys.length}`, tone: getModelPillTone(filled, keys.length) } ], dotClass: getCompletionDotClass(filled, keys.length) }; }
  function getInputSectionStats(inputValue) { const selectedTasks = Array.isArray(inputValue?.task)?inputValue.task.filter(Boolean).length:0; const extraInput = inputValue && typeof inputValue==='object' ? Object.fromEntries(Object.entries(inputValue).filter(([key])=>key!=='task')) : {}; const extraStats = getDirectFieldCompletion(extraInput); const total = 1 + (Object.keys(extraInput).length ? extraStats.total : 0); const filled = (selectedTasks>0?1:0) + (Object.keys(extraInput).length ? extraStats.filled : 0); return { filled, total, subtitle:'Tasks and input filters', badges:[ { text: `Required ${selectedTasks>0?1:0}/1`, tone: selectedTasks>0 ? 'success' : 'warning' }, { text: `Selected ${selectedTasks}`, tone: selectedTasks>0 ? 'success' : 'neutral' } ], dotClass: getCompletionDotClass(filled,total) }; }
  function getNodesSectionStats(nodes){ const list = Array.isArray(nodes)?nodes:[]; const readyNodes = list.filter(node => { const checks=[ Boolean(node?.Level), Boolean(node?.Name), Array.isArray(node?.GroupBy)&&node.GroupBy.length>0, Boolean(node?.Model?.Type), Array.isArray(node?.Model?.X)&&node.Model.X.length>0 ]; return checks.every(Boolean); }).length; const total = list.length>0 ? list.length : 1; const filled = readyNodes; return { filled, total, subtitle: list.length>0 ? 'Nodes, transforms, design and contrasts' : 'No nodes yet. Use + Add Node to create the first node', badges:[ { text: `Required ${list.length>0?1:0}/1`, tone: list.length>0 ? 'success' : 'warning' }, { text: `Ready ${readyNodes}/${list.length||0}`, tone: list.length>0 ? getModelPillTone(readyNodes,list.length) : 'neutral' }, { text: `Nodes ${list.length}`, tone: 'neutral' } ], dotClass: getCompletionDotClass(filled,total) }; }
  function getEdgesSectionStats(edges){ const list = Array.isArray(edges)?edges:[]; const ready = list.filter(edge => Boolean(edge?.Source) && Boolean(edge?.Destination)).length; const total = list.length>0 ? list.length : 1; return { filled: ready, total, subtitle: 'Source to destination node links', badges:[ { text: `Edges ${list.length}`, tone: list.length ? 'success' : 'neutral' }, { text: `Ready ${ready}/${list.length||0}`, tone: list.length ? getModelPillTone(ready, list.length) : 'neutral' } ], dotClass: getCompletionDotClass(ready, total) }; }

  function normalizeEditorStringArray(value) {
    return Array.isArray(value)
      ? value.map(item => String(item || '').trim()).filter(Boolean)
      : [];
  }

  function getNodeWorkspaceLabel(node, idx) {
    return node?.Name || `node_${idx + 1}`;
  }

  function getNodeWorkspaceLevel(node) {
    return node?.Level || 'Run';
  }

  function ensureWorkspaceNodeModel(node) {
    if (!node.Model || typeof node.Model !== 'object' || Array.isArray(node.Model)) {
      node.Model = { Type: 'glm', X: [] };
    }
    if (!Array.isArray(node.Model.X)) node.Model.X = [];
    if (!node.Model.Type) node.Model.Type = 'glm';
    return node.Model;
  }

  function createWorkspacePanel(title, hint) {
    const panel = document.createElement('section');
    panel.className = 'model-node-panel';

    const header = document.createElement('div');
    header.className = 'model-node-panel-header';

    const heading = document.createElement('div');
    const titleEl = document.createElement('div');
    titleEl.className = 'model-node-panel-title';
    titleEl.textContent = title;
    heading.appendChild(titleEl);

    if (hint) {
      const hintEl = document.createElement('div');
      hintEl.className = 'model-node-panel-hint';
      hintEl.textContent = hint;
      heading.appendChild(hintEl);
    }

    const actions = document.createElement('div');
    actions.className = 'd-flex flex-wrap gap-2';

    header.appendChild(heading);
    header.appendChild(actions);
    panel.appendChild(header);

    const body = document.createElement('div');
    body.className = 'd-flex flex-column gap-2';
    panel.appendChild(body);

    return { panel, actions, body };
  }

  function renderNodeGroupByPanel(container, node, idx) {
    const current = Array.isArray(node.GroupBy) ? node.GroupBy.slice() : [];
    const groupBy = Array.from(new Set(current));
    node.GroupBy = groupBy;

    const panel = createWorkspacePanel('GroupBy', 'Define how this node aggregates data before fitting the model.');

    const chips = document.createElement('div');
    chips.className = 'model-node-chip-row';
    if (!groupBy.length) {
      chips.appendChild(createInlineNote('No grouping fields set yet. Run-level nodes typically use run and subject.'));
    } else {
      groupBy.forEach((value, valueIdx) => {
        const chip = document.createElement('span');
        chip.className = 'model-node-chip';
        chip.textContent = value;

        const rm = document.createElement('button');
        rm.type = 'button';
        rm.setAttribute('aria-label', `Remove ${value}`);
        rm.innerHTML = '&times;';
        rm.addEventListener('click', () => {
          node.GroupBy.splice(valueIdx, 1);
          renderModelAccordionEditor();
          setModelEditorStatus('GroupBy updated.', 'info');
        });
        chip.appendChild(rm);
        chips.appendChild(chip);
      });
    }
    panel.body.appendChild(chips);

    const quick = document.createElement('div');
    quick.className = 'd-flex flex-wrap gap-2';
    Array.from(new Set([...(modelEditorGroupByOptions || []), 'run', 'session', 'subject', 'contrast'])).forEach(option => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm btn-outline-secondary';
      btn.textContent = option;
      btn.disabled = node.GroupBy.includes(option);
      btn.addEventListener('click', () => {
        node.GroupBy.push(option);
        renderModelAccordionEditor();
        setModelEditorStatus('GroupBy updated.', 'info');
      });
      quick.appendChild(btn);
    });
    panel.body.appendChild(quick);

    const addRow = document.createElement('div');
    addRow.className = 'd-flex gap-2';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'form-control form-control-sm';
    input.placeholder = 'Add custom metadata key';
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-sm btn-outline-secondary';
    addBtn.textContent = 'Add';
    addBtn.addEventListener('click', () => {
      const value = input.value.trim();
      if (!value) return;
      if (!node.GroupBy.includes(value)) node.GroupBy.push(value);
      renderModelAccordionEditor();
      setModelEditorStatus('GroupBy updated.', 'info');
    });
    addRow.appendChild(input);
    addRow.appendChild(addBtn);
    panel.body.appendChild(addRow);

    container.appendChild(panel.panel);
  }

  function ensureNodeTransformationsObject(node) {
    if (!node.Transformations || typeof node.Transformations !== 'object' || Array.isArray(node.Transformations)) {
      node.Transformations = { Transformer: 'pybids-transforms-v1', Instructions: [], GeneratedColumns: [] };
    }
    if (!Array.isArray(node.Transformations.Instructions)) node.Transformations.Instructions = [];
    if (!Array.isArray(node.Transformations.GeneratedColumns)) node.Transformations.GeneratedColumns = [];
    if (!node.Transformations.Transformer) node.Transformations.Transformer = 'pybids-transforms-v1';
    return node.Transformations;
  }

  function getInlineTransformerColumnSuggestions(node) {
    const eventSamples = (window.modelEditorEventSamples && typeof window.modelEditorEventSamples === 'object')
      ? window.modelEditorEventSamples
      : { trial_type: [], condition: [] };
    const inferredEventColumns = [];
    if (normalizeEditorStringArray(eventSamples.trial_type).length) inferredEventColumns.push('trial_type');
    if (normalizeEditorStringArray(eventSamples.condition).length) inferredEventColumns.push('condition');

    const fromModelX = normalizeEditorStringArray(node?.Model?.X).map(value => {
      if (value === '1') return '';
      if (value.startsWith('trial_type.')) return 'trial_type';
      if (value.startsWith('condition.')) return 'condition';
      return value;
    }).filter(Boolean);

    const fromTransformGenerated = normalizeEditorStringArray(node?.Transformations?.GeneratedColumns);
    const fromGlobalPool = normalizeEditorStringArray(window.modelEditorInterestRegressors)
      .map(value => {
        if (value.startsWith('trial_type.')) return 'trial_type';
        if (value.startsWith('condition.')) return 'condition';
        return value;
      })
      .filter(Boolean);

    return Array.from(new Set([
      ...inferredEventColumns,
      ...fromModelX,
      ...fromTransformGenerated,
      ...fromGlobalPool
    ])).sort((a, b) => a.localeCompare(b));
  }

  function createTransformerInstructionTemplate(opName) {
    switch (opName) {
      case 'Filter':
        return { Name: 'Filter', Input: '', Query: '', Output: '' };
      case 'Concatenate':
        return { Name: 'Concatenate', Input: [], Output: '' };
      case 'Factor':
        return { Name: 'Factor', Input: [] };
      case 'Replace':
        return { Name: 'Replace', Input: '', Replace: [{ key: '', value: '' }], Output: '' };
      case 'Copy':
        return { Name: 'Copy', Input: [], Output: [] };
      case 'Select':
        return { Name: 'Select', Input: [] };
      case 'Delete':
        return { Name: 'Delete', Input: [] };
      case 'Scale':
        return { Name: 'Scale', Input: [], Demean: true, Rescale: true, Output: '' };
      case 'Mean':
        return { Name: 'Mean', Input: '', OmitNan: false, Output: '' };
      case 'Threshold':
        return { Name: 'Threshold', Input: '', Threshold: 0, Binarize: false, Above: true, Output: '' };
      default:
        return { Name: opName };
    }
  }

  function inferFactorGeneratedColumns(inputs) {
    const normalizedInputs = normalizeEditorStringArray(inputs);
    if (!normalizedInputs.length) return [];

    const eventSamples = (window.modelEditorEventSamples && typeof window.modelEditorEventSamples === 'object')
      ? window.modelEditorEventSamples
      : { trial_type: [], condition: [] };

    const levelSets = normalizedInputs.map(column => {
      if (column === 'trial_type') return normalizeEditorStringArray(eventSamples.trial_type);
      if (column === 'condition') return normalizeEditorStringArray(eventSamples.condition);
      return [];
    });

    const hasConcreteLevels = levelSets.every(levels => levels.length > 0);
    if (!hasConcreteLevels) {
      return normalizedInputs.map(column => `${column}_*`);
    }

    const names = [];
    const build = (index, parts) => {
      if (index >= normalizedInputs.length) {
        names.push(parts.join('_'));
        return;
      }
      const column = normalizedInputs[index];
      levelSets[index].forEach(level => {
        build(index + 1, [...parts, column, level]);
      });
    };
    build(0, []);
    return names;
  }

  function inferGeneratedColumnsFromInstruction(instruction) {
    if (!instruction || typeof instruction !== 'object') return [];
    const opName = String(instruction.Name || '').trim();
    const outputValues = normalizeEditorStringArray(instruction.Output);

    if (opName === 'Factor') {
      return inferFactorGeneratedColumns(instruction.Input);
    }

    if (outputValues.length) return outputValues;
    return [];
  }

  function refreshNodeGeneratedColumnsFromInstructions(node) {
    const transformations = ensureNodeTransformationsObject(node);
    const generated = [];
    transformations.Instructions.forEach(instruction => {
      inferGeneratedColumnsFromInstruction(instruction).forEach(name => generated.push(name));
    });
    transformations.GeneratedColumns = Array.from(new Set(normalizeEditorStringArray(generated)));
  }

  function renderNodeTransformationsPanel(container, node, idx) {
    const panel = createWorkspacePanel('Transformations', 'Define transformer operations for this node directly in Model Editor.');
    const path = `Nodes[${idx}].Transformations`;
    const transformations = ensureNodeTransformationsObject(node);

    const suggestionListId = `transformer-col-suggestions-${idx}`;
    const columnSuggestions = getInlineTransformerColumnSuggestions(node);

    function rerender(message = '') {
      refreshNodeGeneratedColumnsFromInstructions(node);
      renderModelAccordionEditor();
      if (message) setModelEditorStatus(message, 'info');
    }

    function addTextField(parent, options) {
      const group = document.createElement('div');
      group.className = 'd-flex flex-column gap-1';
      const label = document.createElement('label');
      label.className = 'form-label small mb-0';
      label.textContent = options.label;
      const input = document.createElement('input');
      input.type = options.type || 'text';
      input.className = 'form-control form-control-sm';
      input.placeholder = options.placeholder || '';
      input.value = options.value || '';
      if (options.useSuggestions) input.setAttribute('list', suggestionListId);
      input.addEventListener('change', () => {
        options.onChange(input.value);
      });
      group.appendChild(label);
      group.appendChild(input);
      if (options.hint) {
        const hint = document.createElement('div');
        hint.className = 'small text-muted';
        hint.textContent = options.hint;
        group.appendChild(hint);
      }
      parent.appendChild(group);
    }

    function addCheckboxField(parent, options) {
      const wrap = document.createElement('div');
      wrap.className = 'form-check';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'form-check-input';
      input.checked = Boolean(options.value);
      const id = `transformer-${idx}-${options.key}-${Math.random().toString(36).slice(2, 7)}`;
      input.id = id;
      const label = document.createElement('label');
      label.className = 'form-check-label small';
      label.htmlFor = id;
      label.textContent = options.label;
      input.addEventListener('change', () => options.onChange(input.checked));
      wrap.appendChild(input);
      wrap.appendChild(label);
      parent.appendChild(wrap);
    }

    function renderReplaceRows(parent, instruction, instIdx) {
      if (!Array.isArray(instruction.Replace)) instruction.Replace = [];
      if (!instruction.Replace.length) instruction.Replace.push({ key: '', value: '' });

      const table = document.createElement('table');
      table.className = 'table table-sm table-bordered mb-1';
      const thead = document.createElement('thead');
      thead.innerHTML = '<tr><th>Old value</th><th>New value</th><th style="width:50px;"></th></tr>';
      table.appendChild(thead);
      const tbody = document.createElement('tbody');

      instruction.Replace.forEach((row, rowIdx) => {
        const tr = document.createElement('tr');

        const keyTd = document.createElement('td');
        const keyInput = document.createElement('input');
        keyInput.type = 'text';
        keyInput.className = 'form-control form-control-sm';
        keyInput.value = String(row?.key || '');
        keyInput.addEventListener('change', () => {
          instruction.Replace[rowIdx].key = keyInput.value;
          rerender();
        });
        keyTd.appendChild(keyInput);

        const valueTd = document.createElement('td');
        const valueInput = document.createElement('input');
        valueInput.type = 'text';
        valueInput.className = 'form-control form-control-sm';
        valueInput.value = String(row?.value || '');
        valueInput.addEventListener('change', () => {
          instruction.Replace[rowIdx].value = valueInput.value;
          rerender();
        });
        valueTd.appendChild(valueInput);

        const removeTd = document.createElement('td');
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-sm btn-outline-danger';
        removeBtn.textContent = 'x';
        removeBtn.addEventListener('click', () => {
          instruction.Replace.splice(rowIdx, 1);
          rerender('Replacement row removed.');
        });
        removeTd.appendChild(removeBtn);

        tr.appendChild(keyTd);
        tr.appendChild(valueTd);
        tr.appendChild(removeTd);
        tbody.appendChild(tr);
      });

      table.appendChild(tbody);
      parent.appendChild(table);

      const addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'btn btn-sm btn-outline-secondary';
      addBtn.textContent = '+ Add replacement row';
      addBtn.addEventListener('click', () => {
        instruction.Replace.push({ key: '', value: '' });
        rerender('Replacement row added.');
      });
      parent.appendChild(addBtn);
    }

    function renderInstructionCard(opName, instruction, instIdx) {
      const card = document.createElement('div');
      card.className = 'me-transformer-op-card';

      const header = document.createElement('div');
      header.className = 'me-transformer-op-header';

      const title = document.createElement('div');
      title.className = 'small fw-bold';
      title.textContent = `${instIdx + 1}. ${opName}`;
      header.appendChild(title);

      const controls = document.createElement('div');
      controls.className = 'd-flex gap-1';

      const upBtn = document.createElement('button');
      upBtn.type = 'button';
      upBtn.className = 'btn btn-sm btn-outline-secondary';
      upBtn.textContent = 'Up';
      upBtn.disabled = instIdx === 0;
      upBtn.addEventListener('click', () => {
        const instructions = transformations.Instructions;
        [instructions[instIdx - 1], instructions[instIdx]] = [instructions[instIdx], instructions[instIdx - 1]];
        rerender('Instruction moved.');
      });

      const downBtn = document.createElement('button');
      downBtn.type = 'button';
      downBtn.className = 'btn btn-sm btn-outline-secondary';
      downBtn.textContent = 'Down';
      downBtn.disabled = instIdx === transformations.Instructions.length - 1;
      downBtn.addEventListener('click', () => {
        const instructions = transformations.Instructions;
        [instructions[instIdx + 1], instructions[instIdx]] = [instructions[instIdx], instructions[instIdx + 1]];
        rerender('Instruction moved.');
      });

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-sm btn-outline-danger';
      removeBtn.textContent = 'Remove';
      removeBtn.addEventListener('click', () => {
        transformations.Instructions.splice(instIdx, 1);
        rerender('Instruction removed.');
      });

      controls.appendChild(upBtn);
      controls.appendChild(downBtn);
      controls.appendChild(removeBtn);
      header.appendChild(controls);
      card.appendChild(header);

      const body = document.createElement('div');
      body.className = 'me-transformer-op-body';

      const setSingle = (field, rawValue) => {
        instruction[field] = parseCsvValues(rawValue)[0] || '';
        rerender();
      };
      const setMulti = (field, rawValue) => {
        instruction[field] = parseCsvValues(rawValue);
        rerender();
      };
      const setOutput = (rawValue) => {
        if (opName === 'Copy') {
          instruction.Output = parseCsvValues(rawValue);
        } else {
          instruction.Output = parseCsvValues(rawValue)[0] || '';
        }
        rerender();
      };

      if (opName === 'Filter') {
        addTextField(body, {
          label: 'Input column',
          value: String(instruction.Input || ''),
          placeholder: 'trial_type',
          useSuggestions: true,
          onChange: (value) => setSingle('Input', value)
        });
        addTextField(body, {
          label: 'Query',
          value: String(instruction.Query || ''),
          placeholder: "trial_type == 'go'",
          onChange: (value) => {
            instruction.Query = String(value || '').trim();
            rerender();
          }
        });
        addTextField(body, {
          label: 'Output (optional)',
          value: String(instruction.Output || ''),
          placeholder: 'filtered_col',
          useSuggestions: true,
          onChange: setOutput
        });
      } else if (opName === 'Concatenate') {
        addTextField(body, {
          label: 'Input columns (comma-separated)',
          value: normalizeEditorStringArray(instruction.Input).join(', '),
          placeholder: 'trial_type, condition',
          useSuggestions: true,
          onChange: (value) => setMulti('Input', value)
        });
        addTextField(body, {
          label: 'Output',
          value: String(instruction.Output || ''),
          placeholder: 'trial_combined',
          onChange: setOutput
        });
      } else if (opName === 'Factor') {
        addTextField(body, {
          label: 'Input columns (comma-separated)',
          value: normalizeEditorStringArray(instruction.Input).join(', '),
          placeholder: 'trial_type',
          useSuggestions: true,
          onChange: (value) => setMulti('Input', value)
        });
      } else if (opName === 'Replace') {
        addTextField(body, {
          label: 'Input column',
          value: String(instruction.Input || ''),
          placeholder: 'trial_type',
          useSuggestions: true,
          onChange: (value) => setSingle('Input', value)
        });
        renderReplaceRows(body, instruction, instIdx);
        addTextField(body, {
          label: 'Output (optional)',
          value: String(instruction.Output || ''),
          placeholder: 'trial_type_clean',
          onChange: setOutput
        });
      } else if (opName === 'Copy') {
        addTextField(body, {
          label: 'Input columns (comma-separated)',
          value: normalizeEditorStringArray(instruction.Input).join(', '),
          placeholder: 'trial_type, condition',
          useSuggestions: true,
          onChange: (value) => setMulti('Input', value)
        });
        addTextField(body, {
          label: 'Output names (comma-separated)',
          value: normalizeEditorStringArray(instruction.Output).join(', '),
          placeholder: 'trial_type_copy, condition_copy',
          onChange: setOutput
        });
      } else if (opName === 'Select' || opName === 'Delete') {
        addTextField(body, {
          label: `${opName === 'Select' ? 'Columns to keep' : 'Columns to delete'} (comma-separated)`,
          value: normalizeEditorStringArray(instruction.Input).join(', '),
          placeholder: 'trial_type, duration',
          useSuggestions: true,
          onChange: (value) => setMulti('Input', value)
        });
      } else if (opName === 'Scale') {
        addTextField(body, {
          label: 'Input columns (comma-separated)',
          value: normalizeEditorStringArray(instruction.Input).join(', '),
          placeholder: 'response_time',
          useSuggestions: true,
          onChange: (value) => setMulti('Input', value)
        });
        addCheckboxField(body, {
          key: 'Demean',
          label: 'Demean',
          value: instruction.Demean !== false,
          onChange: (checked) => {
            instruction.Demean = checked;
            rerender();
          }
        });
        addCheckboxField(body, {
          key: 'Rescale',
          label: 'Rescale (divide by SD)',
          value: instruction.Rescale !== false,
          onChange: (checked) => {
            instruction.Rescale = checked;
            rerender();
          }
        });
        addTextField(body, {
          label: 'Output (optional)',
          value: String(instruction.Output || ''),
          placeholder: 'scaled_col',
          onChange: setOutput
        });
      } else if (opName === 'Mean') {
        addTextField(body, {
          label: 'Input column',
          value: String(instruction.Input || ''),
          placeholder: 'response_time',
          useSuggestions: true,
          onChange: (value) => setSingle('Input', value)
        });
        addCheckboxField(body, {
          key: 'OmitNan',
          label: 'Omit NaN',
          value: Boolean(instruction.OmitNan),
          onChange: (checked) => {
            instruction.OmitNan = checked;
            rerender();
          }
        });
        addTextField(body, {
          label: 'Output (optional)',
          value: String(instruction.Output || ''),
          placeholder: 'mean_col',
          onChange: setOutput
        });
      } else if (opName === 'Threshold') {
        addTextField(body, {
          label: 'Input column',
          value: String(instruction.Input || ''),
          placeholder: 'response_time',
          useSuggestions: true,
          onChange: (value) => setSingle('Input', value)
        });
        addTextField(body, {
          label: 'Threshold value',
          type: 'number',
          value: String(instruction.Threshold ?? 0),
          onChange: (value) => {
            const parsed = Number(value);
            instruction.Threshold = Number.isFinite(parsed) ? parsed : 0;
            rerender();
          }
        });
        addCheckboxField(body, {
          key: 'Binarize',
          label: 'Binarize',
          value: Boolean(instruction.Binarize),
          onChange: (checked) => {
            instruction.Binarize = checked;
            rerender();
          }
        });
        addCheckboxField(body, {
          key: 'Above',
          label: 'Keep above threshold',
          value: instruction.Above !== false,
          onChange: (checked) => {
            instruction.Above = checked;
            rerender();
          }
        });
        addTextField(body, {
          label: 'Output (optional)',
          value: String(instruction.Output || ''),
          placeholder: 'thresholded_col',
          onChange: setOutput
        });
      }

      card.appendChild(body);
      return card;
    }

    const instructionCount = Array.isArray(transformations.Instructions) ? transformations.Instructions.length : 0;
    refreshNodeGeneratedColumnsFromInstructions(node);
    const generatedCount = Array.isArray(transformations.GeneratedColumns) ? transformations.GeneratedColumns.length : 0;
    const summary = document.createElement('div');
    summary.className = 'd-flex flex-wrap gap-2';
    appendModelMetaPill(summary, transformations.Transformer || 'pybids-transforms-v1', 'success');
    appendModelMetaPill(summary, `${instructionCount} instruction${instructionCount === 1 ? '' : 's'}`, instructionCount ? 'success' : 'neutral');
    appendModelMetaPill(summary, `${generatedCount} generated`, generatedCount ? 'warning' : 'neutral');
    panel.body.appendChild(summary);

    const builder = document.createElement('div');
    builder.className = 'me-transformer-builder';
    builder.appendChild(createInlineNote('Add and edit operations directly here. Changes are applied to this node immediately.'));

    const datalist = document.createElement('datalist');
    datalist.id = suggestionListId;
    columnSuggestions.forEach(name => {
      const option = document.createElement('option');
      option.value = name;
      datalist.appendChild(option);
    });
    builder.appendChild(datalist);

    const opButtonRow = document.createElement('div');
    opButtonRow.className = 'd-flex flex-wrap gap-1';
    [
      'Filter', 'Concatenate', 'Factor', 'Replace', 'Copy', 'Select', 'Delete',
      'Scale', 'Mean', 'Threshold'
    ].forEach(opName => {
      const addOpBtn = document.createElement('button');
      addOpBtn.type = 'button';
      addOpBtn.className = 'btn btn-sm btn-outline-primary';
      addOpBtn.textContent = `+ ${opName}`;
      addOpBtn.addEventListener('click', () => {
        transformations.Instructions.push(createTransformerInstructionTemplate(opName));
        rerender(`Added ${opName} instruction.`);
      });
      opButtonRow.appendChild(addOpBtn);
    });
    builder.appendChild(opButtonRow);

    const opList = document.createElement('div');
    opList.className = 'me-transformer-op-list';
    if (!transformations.Instructions.length) {
      opList.appendChild(createInlineNote('No instructions yet. Add operations above.'));
    } else {
      transformations.Instructions.forEach((instruction, instIdx) => {
        const opName = String(instruction?.Name || '').trim();
        if (!opName) {
          transformations.Instructions[instIdx] = createTransformerInstructionTemplate('Filter');
        }
        opList.appendChild(renderInstructionCard(String(transformations.Instructions[instIdx].Name || 'Filter'), transformations.Instructions[instIdx], instIdx));
      });
    }
    builder.appendChild(opList);

    const generatedLabel = document.createElement('div');
    generatedLabel.className = 'small fw-bold';
    generatedLabel.textContent = 'Generated JSON Preview';
    builder.appendChild(generatedLabel);

    const jsonPreview = document.createElement('pre');
    jsonPreview.className = 'me-transformer-json';
    jsonPreview.textContent = JSON.stringify(transformations, null, 2);
    builder.appendChild(jsonPreview);

    panel.body.appendChild(builder);

    const advanced = document.createElement('details');
    advanced.className = 'mt-1';
    const advSummary = document.createElement('summary');
    advSummary.className = 'small fw-bold';
    advSummary.textContent = 'Advanced Transformations JSON';
    advanced.appendChild(advSummary);
    const advWrap = document.createElement('div');
    advWrap.className = 'mt-2';
    renderJsonEditor(advWrap, node.Transformations, path, false, 0);
    advanced.appendChild(advWrap);
    panel.body.appendChild(advanced);

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'btn btn-sm btn-outline-danger';
    clearBtn.textContent = 'Remove Transformations';
    clearBtn.addEventListener('click', () => {
      delete node.Transformations;
      renderModelAccordionEditor();
      setModelEditorStatus('Transformations removed.', 'info');
    });
    panel.actions.appendChild(clearBtn);

    container.appendChild(panel.panel);
  }

  function renderNodeModelPanel(container, node, idx) {
    const panel = createWorkspacePanel('Design Matrix', 'Define Model.Type, Model.X, HRF and advanced model options for this node.');
    ensureWorkspaceNodeModel(node);
    renderJsonEditor(panel.body, node.Model, `Nodes[${idx}].Model`, false, 0);
    container.appendChild(panel.panel);
  }

  function renderNodeDummyContrastsPanel(container, node, idx) {
    const panel = createWorkspacePanel('Dummy Contrasts', 'Generate simple baseline contrasts automatically when appropriate.');
    if (!node.DummyContrasts || typeof node.DummyContrasts !== 'object' || Array.isArray(node.DummyContrasts)) {
      node.DummyContrasts = { Test: 't', Contrasts: [] };
    }

    const testRow = document.createElement('div');
    testRow.className = 'row g-2';
    const testCol = document.createElement('div');
    testCol.className = 'col-md-4';
    const testLabel = document.createElement('label');
    testLabel.className = 'form-label small mb-1';
    testLabel.textContent = 'Test';
    const testSelect = document.createElement('select');
    testSelect.className = 'form-select form-select-sm';
    ['t', 'F'].forEach(value => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      testSelect.appendChild(option);
    });
    testSelect.value = node.DummyContrasts.Test || 't';
    testSelect.addEventListener('change', () => {
      node.DummyContrasts.Test = testSelect.value;
      setModelEditorStatus('Dummy contrasts updated.', 'info');
    });
    testCol.appendChild(testLabel);
    testCol.appendChild(testSelect);
    testRow.appendChild(testCol);

    const contrastsCol = document.createElement('div');
    contrastsCol.className = 'col-md-8';
    const contrastsLabel = document.createElement('label');
    contrastsLabel.className = 'form-label small mb-1';
    contrastsLabel.textContent = 'Contrasts';
    const contrastsInput = document.createElement('input');
    contrastsInput.type = 'text';
    contrastsInput.className = 'form-control form-control-sm';
    contrastsInput.placeholder = 'trial_type.go, trial_type.stop';
    contrastsInput.value = normalizeEditorStringArray(node.DummyContrasts.Contrasts).join(', ');
    contrastsInput.addEventListener('change', () => {
      node.DummyContrasts.Contrasts = parseCsvValues(contrastsInput.value);
      renderModelAccordionEditor();
      setModelEditorStatus('Dummy contrasts updated.', 'info');
    });
    contrastsCol.appendChild(contrastsLabel);
    contrastsCol.appendChild(contrastsInput);
    testRow.appendChild(contrastsCol);
    panel.body.appendChild(testRow);

    container.appendChild(panel.panel);
  }

  function renderNodeContrastsPanel(container, node, idx) {
    const panel = createWorkspacePanel('Contrasts', 'Define named contrasts over the current node design matrix.');
    if (!Array.isArray(node.Contrasts)) node.Contrasts = [];

    if (!node.Contrasts.length) {
      panel.body.appendChild(createInlineNote('No explicit contrasts defined yet.'));
    }

    node.Contrasts.forEach((contrast, contrastIdx) => {
      if (!contrast || typeof contrast !== 'object') {
        node.Contrasts[contrastIdx] = contrast = { Name: '', ConditionList: [], Weights: [], Test: 't' };
      }

      const card = document.createElement('div');
      card.className = 'model-contrast-card';

      const top = document.createElement('div');
      top.className = 'd-flex justify-content-between align-items-start gap-2 mb-2';
      const title = document.createElement('div');
      title.className = 'small fw-bold';
      title.textContent = contrast.Name || `Contrast ${contrastIdx + 1}`;
      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-sm btn-outline-danger';
      removeBtn.innerHTML = '<i class="fas fa-trash"></i>';
      removeBtn.addEventListener('click', () => {
        node.Contrasts.splice(contrastIdx, 1);
        renderModelAccordionEditor();
        setModelEditorStatus('Contrast removed.', 'info');
      });
      top.appendChild(title);
      top.appendChild(removeBtn);
      card.appendChild(top);

      const grid = document.createElement('div');
      grid.className = 'row g-2';

      const nameCol = document.createElement('div');
      nameCol.className = 'col-md-6';
      const nameLabel = document.createElement('label');
      nameLabel.className = 'form-label small mb-1';
      nameLabel.textContent = 'Name';
      const nameInput = document.createElement('input');
      nameInput.type = 'text';
      nameInput.className = 'form-control form-control-sm';
      nameInput.value = contrast.Name || '';
      nameInput.addEventListener('change', () => {
        contrast.Name = nameInput.value.trim();
        renderModelAccordionEditor();
        setModelEditorStatus('Contrast updated.', 'info');
      });
      nameCol.appendChild(nameLabel);
      nameCol.appendChild(nameInput);

      const testCol = document.createElement('div');
      testCol.className = 'col-md-2';
      const testLabel = document.createElement('label');
      testLabel.className = 'form-label small mb-1';
      testLabel.textContent = 'Test';
      const testSelect = document.createElement('select');
      testSelect.className = 'form-select form-select-sm';
      ['t', 'F'].forEach(value => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        testSelect.appendChild(option);
      });
      testSelect.value = contrast.Test || 't';
      testSelect.addEventListener('change', () => {
        contrast.Test = testSelect.value;
        setModelEditorStatus('Contrast updated.', 'info');
      });
      testCol.appendChild(testLabel);
      testCol.appendChild(testSelect);

      const conditionCol = document.createElement('div');
      conditionCol.className = 'col-12';
      const conditionLabel = document.createElement('label');
      conditionLabel.className = 'form-label small mb-1';
      conditionLabel.textContent = 'ConditionList';
      const conditionInput = document.createElement('input');
      conditionInput.type = 'text';
      conditionInput.className = 'form-control form-control-sm';
      conditionInput.placeholder = 'trial_type.go, trial_type.stop';
      conditionInput.value = normalizeEditorStringArray(contrast.ConditionList).join(', ');
      conditionInput.addEventListener('change', () => {
        contrast.ConditionList = parseCsvValues(conditionInput.value);
        renderModelAccordionEditor();
        setModelEditorStatus('Contrast updated.', 'info');
      });
      conditionCol.appendChild(conditionLabel);
      conditionCol.appendChild(conditionInput);

      const weightCol = document.createElement('div');
      weightCol.className = 'col-12';
      const weightLabel = document.createElement('label');
      weightLabel.className = 'form-label small mb-1';
      weightLabel.textContent = 'Weights';
      const weightInput = document.createElement('input');
      weightInput.type = 'text';
      weightInput.className = 'form-control form-control-sm';
      weightInput.placeholder = '1, -1';
      weightInput.value = Array.isArray(contrast.Weights) ? contrast.Weights.join(', ') : '';
      weightInput.addEventListener('change', () => {
        contrast.Weights = parseCsvValues(weightInput.value).map(value => {
          const num = Number(value);
          return Number.isNaN(num) ? value : num;
        });
        renderModelAccordionEditor();
        setModelEditorStatus('Contrast updated.', 'info');
      });
      weightCol.appendChild(weightLabel);
      weightCol.appendChild(weightInput);

      grid.appendChild(nameCol);
      grid.appendChild(testCol);
      grid.appendChild(conditionCol);
      grid.appendChild(weightCol);
      card.appendChild(grid);

      const mismatch = Array.isArray(contrast.ConditionList) && Array.isArray(contrast.Weights) && contrast.ConditionList.length !== contrast.Weights.length;
      if (mismatch) {
        const note = document.createElement('div');
        note.className = 'small text-warning mt-2';
        note.textContent = 'ConditionList and Weights should have the same length.';
        card.appendChild(note);
      }

      panel.body.appendChild(card);
    });

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-sm btn-outline-primary';
    addBtn.textContent = 'Add Contrast';
    addBtn.addEventListener('click', () => {
      node.Contrasts.push({ Name: '', ConditionList: [], Weights: [], Test: 't' });
      renderModelAccordionEditor();
      setModelEditorStatus('Contrast added.', 'info');
    });
    panel.actions.appendChild(addBtn);

    container.appendChild(panel.panel);
  }

  function createNodeWorkspaceCard(node, idx) {
    if (!Array.isArray(node.GroupBy)) node.GroupBy = [];

    const card = document.createElement('div');
    const selected = currentSelection?.type === 'nodeField' && Number(currentSelection.idx) === idx;
    card.className = `model-node-card${selected ? ' is-selected' : ''}`;

    const header = document.createElement('div');
    header.className = 'model-node-card-header';

    const title = document.createElement('div');
    title.className = 'model-node-card-title';
    const index = document.createElement('span');
    index.className = 'model-node-index';
    index.textContent = String(idx + 1);
    const heading = document.createElement('div');
    heading.className = 'd-flex flex-column gap-1';
    const strong = document.createElement('strong');
    strong.textContent = getNodeWorkspaceLabel(node, idx);
    const meta = document.createElement('div');
    meta.className = 'd-flex flex-wrap gap-2';
    appendModelMetaPill(meta, getNodeWorkspaceLevel(node), 'success');
    appendModelMetaPill(meta, `${normalizeEditorStringArray(node.GroupBy).length} group by`, normalizeEditorStringArray(node.GroupBy).length ? 'warning' : 'neutral');
    appendModelMetaPill(meta, `${Array.isArray(node.Model?.X) ? node.Model.X.length : 0} regressors`, Array.isArray(node.Model?.X) && node.Model.X.length ? 'success' : 'neutral');
    appendModelMetaPill(meta, `${Array.isArray(node.Contrasts) ? node.Contrasts.length : 0} contrasts`, Array.isArray(node.Contrasts) && node.Contrasts.length ? 'success' : 'neutral');
    heading.appendChild(strong);
    heading.appendChild(meta);
    title.appendChild(index);
    title.appendChild(heading);
    header.appendChild(title);

    const actions = document.createElement('div');
    actions.className = 'd-flex gap-2';
    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'btn btn-sm btn-outline-secondary';
    upBtn.innerHTML = '<i class="fas fa-arrow-up"></i>';
    upBtn.disabled = idx === 0;
    upBtn.addEventListener('click', () => {
      moveArrayItem(`Nodes[${idx}]`, 'up');
      renderModelAccordionEditor();
      setModelEditorStatus('Node order updated.', 'info');
    });
    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'btn btn-sm btn-outline-secondary';
    downBtn.innerHTML = '<i class="fas fa-arrow-down"></i>';
    downBtn.disabled = idx === ((Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes.length : 1) - 1);
    downBtn.addEventListener('click', () => {
      moveArrayItem(`Nodes[${idx}]`, 'down');
      renderModelAccordionEditor();
      setModelEditorStatus('Node order updated.', 'info');
    });
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn btn-sm btn-outline-danger';
    removeBtn.innerHTML = '<i class="fas fa-trash"></i>';
    removeBtn.addEventListener('click', () => {
      removeArrayItem(`Nodes[${idx}]`);
      renderModelAccordionEditor();
      setModelEditorStatus('Node removed.', 'info');
    });
    actions.appendChild(upBtn);
    actions.appendChild(downBtn);
    actions.appendChild(removeBtn);
    header.appendChild(actions);
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'model-node-card-body';

    const basics = document.createElement('div');
    basics.className = 'model-node-grid';

    const levelWrap = document.createElement('div');
    const levelLabel = document.createElement('label');
    levelLabel.className = 'form-label small mb-1';
    levelLabel.textContent = 'Level';
    const levelSelect = document.createElement('select');
    levelSelect.className = 'form-select form-select-sm';
    ['Run', 'Session', 'Subject', 'Dataset'].forEach(level => {
      const option = document.createElement('option');
      option.value = level;
      option.textContent = level;
      levelSelect.appendChild(option);
    });
    const rawLevel = String(node.Level || 'Run');
    levelSelect.value = ['Run', 'Session', 'Subject', 'Dataset'].find(level => level.toLowerCase() === rawLevel.toLowerCase()) || 'Run';
    levelSelect.addEventListener('change', () => {
      node.Level = levelSelect.value;
      currentSelection = { type: 'nodeField', idx, field: 'Level' };
      window.currentSelection = currentSelection;
      selectedLabel.textContent = `${node.Level} — ${getNodeWorkspaceLabel(node, idx)}`;
      selectedMeta.textContent = 'Node workspace';
      renderModelStructure();
      renderNodeList();
      renderModelAccordionEditor();
      setModelEditorStatus('Node level updated.', 'info');
    });
    levelWrap.appendChild(levelLabel);
    levelWrap.appendChild(levelSelect);

    const nameWrap = document.createElement('div');
    const nameLabel = document.createElement('label');
    nameLabel.className = 'form-label small mb-1';
    nameLabel.textContent = 'Name';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'form-control form-control-sm';
    nameInput.placeholder = `node_${idx + 1}`;
    nameInput.value = node.Name || '';
    nameInput.addEventListener('change', () => {
      node.Name = nameInput.value.trim();
      currentSelection = { type: 'nodeField', idx, field: 'Name' };
      window.currentSelection = currentSelection;
      selectedLabel.textContent = `${getNodeWorkspaceLevel(node)} — ${getNodeWorkspaceLabel(node, idx)}`;
      selectedMeta.textContent = 'Node workspace';
      renderModelStructure();
      renderNodeList();
      renderModelAccordionEditor();
      setModelEditorStatus('Node name updated.', 'info');
    });
    nameWrap.appendChild(nameLabel);
    nameWrap.appendChild(nameInput);

    basics.appendChild(levelWrap);
    basics.appendChild(nameWrap);
    body.appendChild(basics);

    renderNodeGroupByPanel(body, node, idx);
    renderNodeTransformationsPanel(body, node, idx);
    renderNodeModelPanel(body, node, idx);
    renderNodeDummyContrastsPanel(body, node, idx);
    renderNodeContrastsPanel(body, node, idx);

    card.appendChild(body);
    return card;
  }

  function renderNodesWorkspace(body) {
    const nodes = Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes : [];
    if (!nodes.length) {
      body.appendChild(createInlineNote('No nodes defined yet. Use Add Node to create the first analysis node.'));
      return;
    }

    const stack = document.createElement('div');
    stack.className = 'model-workspace-stack';
    nodes.forEach((node, idx) => {
      stack.appendChild(createNodeWorkspaceCard(node, idx));
    });
    body.appendChild(stack);
  }

  function getEdgeDefaultValue() {
    const nodes = Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes : [];
    const source = nodes[0]?.Name || '';
    const destination = nodes[1]?.Name || nodes[0]?.Name || '';
    return { Source: source, Destination: destination };
  }

  function renderEdgesWorkspace(body) {
    if (!Array.isArray(modelEditorDraft.Edges)) modelEditorDraft.Edges = [];
    const nodes = Array.isArray(modelEditorDraft?.Nodes) ? modelEditorDraft.Nodes : [];
    const nodeNames = nodes.map((node, idx) => node?.Name || `node_${idx + 1}`);

    const stack = document.createElement('div');
    stack.className = 'model-workspace-stack';

    if (!modelEditorDraft.Edges.length) {
      stack.appendChild(createInlineNote('No edges defined yet. Add an edge to connect nodes in the BIDS model graph.'));
    }

    modelEditorDraft.Edges.forEach((edge, idx) => {
      if (!edge || typeof edge !== 'object') {
        modelEditorDraft.Edges[idx] = edge = getEdgeDefaultValue();
      }

      const card = document.createElement('div');
      card.className = 'model-edge-card';

      const header = document.createElement('div');
      header.className = 'model-edge-card-header';
      const title = document.createElement('div');
      title.className = 'model-edge-card-title';
      const index = document.createElement('span');
      index.className = 'model-edge-index';
      index.textContent = String(idx + 1);
      const heading = document.createElement('div');
      const strong = document.createElement('strong');
      strong.textContent = `${edge.Source || '?'} → ${edge.Destination || '?'}`;
      const hint = document.createElement('div');
      hint.className = 'small text-muted';
      hint.textContent = 'Connect source and destination nodes, optionally filtering propagated contrasts.';
      heading.appendChild(strong);
      heading.appendChild(hint);
      title.appendChild(index);
      title.appendChild(heading);
      header.appendChild(title);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-sm btn-outline-danger';
      removeBtn.innerHTML = '<i class="fas fa-trash"></i>';
      removeBtn.addEventListener('click', () => {
        modelEditorDraft.Edges.splice(idx, 1);
        renderModelAccordionEditor();
        setModelEditorStatus('Edge removed.', 'info');
      });
      header.appendChild(removeBtn);
      card.appendChild(header);

      const bodyWrap = document.createElement('div');
      bodyWrap.className = 'model-edge-card-body';
      const grid = document.createElement('div');
      grid.className = 'model-edge-grid';

      ['Source', 'Destination'].forEach(field => {
        const wrap = document.createElement('div');
        const label = document.createElement('label');
        label.className = 'form-label small mb-1';
        label.textContent = field;
        const select = document.createElement('select');
        select.className = 'form-select form-select-sm';
        const values = Array.from(new Set([edge[field] || '', ...nodeNames])).filter(Boolean);
        values.forEach(value => {
          const option = document.createElement('option');
          option.value = value;
          option.textContent = value;
          select.appendChild(option);
        });
        if (!values.length) {
          const option = document.createElement('option');
          option.value = '';
          option.textContent = 'No nodes available';
          select.appendChild(option);
        }
        select.value = edge[field] || values[0] || '';
        select.addEventListener('change', () => {
          edge[field] = select.value;
          renderModelAccordionEditor();
          setModelEditorStatus('Edge updated.', 'info');
        });
        wrap.appendChild(label);
        wrap.appendChild(select);
        grid.appendChild(wrap);
      });
      bodyWrap.appendChild(grid);

      const filterWrap = document.createElement('div');
      const filterLabel = document.createElement('label');
      filterLabel.className = 'form-label small mb-1';
      filterLabel.textContent = 'Filter.contrast (optional)';
      const filterInput = document.createElement('input');
      filterInput.type = 'text';
      filterInput.className = 'form-control form-control-sm';
      filterInput.placeholder = 'contrast_a, contrast_b';
      filterInput.value = normalizeEditorStringArray(edge.Filter?.contrast).join(', ');
      filterInput.addEventListener('change', () => {
        const values = parseCsvValues(filterInput.value);
        if (!values.length) {
          if (edge.Filter && typeof edge.Filter === 'object') {
            delete edge.Filter.contrast;
            if (!Object.keys(edge.Filter).length) delete edge.Filter;
          }
        } else {
          if (!edge.Filter || typeof edge.Filter !== 'object' || Array.isArray(edge.Filter)) edge.Filter = {};
          edge.Filter.contrast = values;
        }
        renderModelAccordionEditor();
        setModelEditorStatus('Edge updated.', 'info');
      });
      filterWrap.appendChild(filterLabel);
      filterWrap.appendChild(filterInput);
      bodyWrap.appendChild(filterWrap);

      card.appendChild(bodyWrap);
      stack.appendChild(card);
    });

    body.appendChild(stack);
  }

  function renderModelSectionContent(body, section) {
    if (section.kind === 'input') { body.appendChild(createModelTaskPicker()); const extraInput = section.value && typeof section.value === 'object' ? Object.fromEntries(Object.entries(section.value).filter(([key])=>key!=='task')) : {}; if (Object.keys(extraInput).length > 0) { renderJsonEditor(body, extraInput, 'Input', false, 0); } else { body.appendChild(createInlineNote('Additional input properties will appear here if the model defines them.')); } return; }
    if (section.kind === 'overview') { renderJsonEditor(body, section.value, '', false, 0); return; }
    if (section.kind === 'nodes') { renderNodesWorkspace(body); return; }
    if (section.kind === 'edges') { renderEdgesWorkspace(body); return; }
    if ((section.kind==='array' || section.kind==='object') && !isFilledModelValue(section.value)) { body.appendChild(createInlineNote(`${section.label} is currently empty.`)); return; }
    renderJsonEditor(body, section.value, section.path, false, 0);
  }

  function createModelSectionCard(container, section) {
    const card = document.createElement('div');
    card.className = 'model-section-card';

    const idBase = `model-section-${section.statePath.replace(/[^a-zA-Z0-9]/g, '-')}`;
    const headerId = `${idBase}-h`;
    const collapseId = `${idBase}-c`;

    const header = document.createElement('h2');
    header.className = 'accordion-header';
    header.id = headerId;

    const headerWrap = document.createElement('div');
    headerWrap.className = 'd-flex align-items-center gap-2';

    const button = document.createElement('button');
    button.className = 'accordion-button model-section-toggle';
    button.type = 'button';
    button.setAttribute('data-bs-toggle', 'collapse');
    button.setAttribute('data-bs-target', `#${collapseId}`);
    button.setAttribute('aria-controls', collapseId);

    const title = document.createElement('span');
    title.className = 'model-section-title';
    const icon = document.createElement('span');
    icon.className = 'model-section-icon';
    icon.innerHTML = `<i class="fas ${section.icon}"></i>`;
    const heading = document.createElement('span');
    heading.className = 'model-section-heading';
    const label = document.createElement('span');
    label.className = 'model-section-label';
    label.textContent = section.label;
    const subtitle = document.createElement('span');
    subtitle.className = 'model-section-subtitle';
    subtitle.textContent = showModelTechnicalPaths && section.path ? section.path : section.stats.subtitle;
    heading.appendChild(label);
    heading.appendChild(subtitle);
    title.appendChild(icon);
    title.appendChild(heading);

    const meta = document.createElement('span');
    meta.className = 'model-section-meta';
    section.stats.badges.forEach(badge => appendModelMetaPill(meta, badge.text, badge.tone));

    button.appendChild(title);
    button.appendChild(meta);
    headerWrap.appendChild(button);

    if (section.kind === 'nodes' || section.kind === 'array' || section.kind === 'edges') {
      if (section.kind === 'nodes') {
        const addNodeFromPreset = (presetValue) => {
          let nodeList = getByPath(modelEditorDraft, section.path);
          if (!Array.isArray(nodeList)) setByPath(modelEditorDraft, section.path, []);
          nodeList = getByPath(modelEditorDraft, section.path);
          if (!Array.isArray(nodeList)) {
            setStatus('Could not create node list for this section.', 'danger');
            return;
          }

          const addResult = buildNodeFromPreset(presetValue);
          nodeList.push(addResult.node);
          const newIndex = nodeList.length - 1;

          let edgeCreated = false;
          if (newIndex > 0) {
            let edgeList = getByPath(modelEditorDraft, 'Edges');
            if (!Array.isArray(edgeList)) setByPath(modelEditorDraft, 'Edges', []);
            edgeList = getByPath(modelEditorDraft, 'Edges');
            if (Array.isArray(edgeList)) {
              const sourceName = String(nodeList[newIndex - 1]?.Name || '').trim();
              const destinationName = String(nodeList[newIndex]?.Name || '').trim();
              if (sourceName && destinationName) {
                const hasEdge = edgeList.some(edge =>
                  String(edge?.Source || '').trim() === sourceName
                  && String(edge?.Destination || '').trim() === destinationName
                );
                if (!hasEdge) {
                  edgeList.push({ Source: sourceName, Destination: destinationName });
                  edgeCreated = true;
                }
              }
            }
          }

          if (window.modelEditorPendingOpenPaths instanceof Set) {
            window.modelEditorPendingOpenPaths.add(section.statePath);
            if (edgeCreated) window.modelEditorPendingOpenPaths.add('Edges');
          }
          renderModelStructure();
          renderNodeList();
          if (addResult.forceFriendly) {
            setRawMode(false);
            ensureSelectionDrivenRightPane();
            selectNodeField(newIndex, addResult.selectField || 'Model');
          } else if (editorMode === 'full') {
            renderModelAccordionEditor();
          } else {
            selectNodeField(newIndex, addResult.selectField || 'Model');
          }
          const edgeNote = edgeCreated ? ' Linked with an edge.' : '';
          setStatus(`${addResult.message}${edgeNote}`, addResult.tone || 'success');
        };

        const addGroup = document.createElement('div');
        addGroup.className = 'btn-group btn-group-sm json-add-btn';

        const quickAddBtn = document.createElement('button');
        quickAddBtn.type = 'button';
        quickAddBtn.className = 'btn btn-sm btn-success';
        quickAddBtn.textContent = '+ Add Node';
        quickAddBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          addNodeFromPreset('run_basic');
        });
        addGroup.appendChild(quickAddBtn);

        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'btn btn-sm btn-success dropdown-toggle dropdown-toggle-split';
        addBtn.innerHTML = '<span class="visually-hidden">Node presets</span>';
        addBtn.setAttribute('data-bs-toggle', 'dropdown');
        addBtn.setAttribute('aria-expanded', 'false');
        addBtn.setAttribute('aria-label', 'Node presets');
        addGroup.appendChild(addBtn);

        const menu = document.createElement('div');
        menu.className = 'dropdown-menu dropdown-menu-end';
        [
          ['run_basic', 'Run node'],
          ['subject_fixed', 'Subject node: fixed effects'],
          ['dataset_basic', 'Dataset node']
        ].forEach(([value, label]) => {
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'dropdown-item';
          item.textContent = label;
          item.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            addNodeFromPreset(value);
          });
          menu.appendChild(item);
        });
        addGroup.appendChild(menu);
        headerWrap.appendChild(addGroup);
      } else {
        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'btn btn-sm btn-outline-success json-add-btn';
        addBtn.textContent = section.kind === 'edges' ? '+ Add Edge' : '+ Add';
        addBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          const current = getByPath(modelEditorDraft, section.path);
          if (!Array.isArray(current)) setByPath(modelEditorDraft, section.path, []);
          if (!Array.isArray(getByPath(modelEditorDraft, section.path))) modelEditorDraft[section.path] = [];
          if (section.kind === 'edges') modelEditorDraft[section.path].push(getEdgeDefaultValue());
          else addArrayItem(section.path);
          renderModelStructure();
          renderNodeList();
          renderModelAccordionEditor();
        });
        headerWrap.appendChild(addBtn);
      }
    }

    header.appendChild(headerWrap);

    const collapse = document.createElement('div');
    collapse.id = collapseId;
    collapse.dataset.jsonPath = section.statePath;
    const wasOpen = modelEditorOpenPaths.has(section.statePath) || (!modelEditorOpenPaths.size && ['overview', 'input', 'nodes', 'edges'].includes(section.kind));
    collapse.className = `accordion-collapse collapse ${wasOpen ? 'show' : ''}`;
    button.className = `accordion-button model-section-toggle ${wasOpen ? '' : 'collapsed'}`;
    button.setAttribute('aria-expanded', wasOpen ? 'true' : 'false');
    collapse.setAttribute('aria-labelledby', headerId);

    const body = document.createElement('div');
    body.className = 'model-section-body';
    renderModelSectionContent(body, section);
    collapse.appendChild(body);

    card.appendChild(header);
    card.appendChild(collapse);
    container.appendChild(card);
  }

  function renderJsonEditor(container, node, basePath = '', inheritedLocked = false, depth = 0) {
    if (Array.isArray(node)) {
      const listWrap = document.createElement('div');
      listWrap.className = 'accordion';

      if (/\.Model\.X$/.test(basePath)) {
        const normalizeList = (value) => Array.isArray(value) ? value.map(v => String(v).trim()).filter(Boolean) : [];
        const modelX = getByPath(modelEditorDraft, basePath);
        const currentRegs = normalizeList(Array.isArray(modelX) ? modelX : node);
        const eventSamples = (window.modelEditorEventSamples && typeof window.modelEditorEventSamples === 'object')
          ? window.modelEditorEventSamples
          : { trial_type: [], condition: [] };
        const selectedTasks = normalizeList(modelEditorDraft?.Input?.task);
        const hasSingleSelectedTask = selectedTasks.length === 1;
        const trialTypeRegressors = hasSingleSelectedTask
          ? normalizeList(eventSamples.trial_type).map(v => `trial_type.${v}`)
          : [];
        const conditionRegressors = hasSingleSelectedTask
          ? normalizeList(eventSamples.condition).map(v => `condition.${v}`)
          : [];
        const confoundColumns = normalizeList(window.modelEditorConfoundColumns);
        const transRotConfounds = normalizeList(window.modelEditorTransRotConfounds);
        const defaultTransRot = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z'];
        const modelPath = basePath.replace(/\.X$/, '');

        function getModelObject(){
          const modelObj = getByPath(modelEditorDraft, modelPath);
          return modelObj && typeof modelObj === 'object' && !Array.isArray(modelObj) ? modelObj : null;
        }

        function getHrfVariables(){
          const modelObj = getModelObject();
          if (!modelObj || !modelObj.HRF || typeof modelObj.HRF !== 'object' || Array.isArray(modelObj.HRF)) return [];
          return normalizeList(modelObj.HRF.Variables);
        }

        function syncHrfVariablesWithModelX(){
          const modelObj = getModelObject();
          if (!modelObj || !modelObj.HRF || typeof modelObj.HRF !== 'object' || Array.isArray(modelObj.HRF)) return;
          const selected = new Set(normalizeList(getByPath(modelEditorDraft, basePath)));
          const kept = getHrfVariables().filter(reg => selected.has(reg));
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

        function isHrfApplicableRegressor(reg){
          return String(reg || '').trim() !== '1';
        }

        function isRegressorHrfEnabled(reg){
          return getHrfVariables().includes(String(reg || '').trim());
        }

        function toggleRegressorHrf(reg){
          const normalized = String(reg || '').trim();
          if (!normalized) return;
          if (!isHrfApplicableRegressor(normalized)) {
            setModelEditorStatus('Intercept is not HRF-convolved.', 'info');
            return;
          }

          const modelObj = getModelObject();
          if (!modelObj) return;
          const enabled = isRegressorHrfEnabled(normalized);
          if (enabled) {
            if (modelObj.HRF && typeof modelObj.HRF === 'object' && !Array.isArray(modelObj.HRF)) {
              const nextVars = getHrfVariables().filter(entry => entry !== normalized);
              if (nextVars.length) {
                modelObj.HRF.Variables = nextVars;
              } else {
                delete modelObj.HRF;
              }
            }
            setModelEditorStatus(`HRF off for ${normalized}`, 'info');
            renderModelAccordionEditor();
            return;
          }

          if (!modelObj.HRF || typeof modelObj.HRF !== 'object' || Array.isArray(modelObj.HRF)) {
            modelObj.HRF = { Model: 'spm', Variables: [] };
          }
          modelObj.HRF.Model = String(modelObj.HRF.Model || 'spm').trim() || 'spm';
          modelObj.HRF.Variables = Array.from(new Set([...getHrfVariables(), normalized]));
          setModelEditorStatus(`HRF on for ${normalized}`, 'info');
          renderModelAccordionEditor();
        }

        function removeModelXRegressor(index){
          const arr = getByPath(modelEditorDraft, basePath);
          if (!Array.isArray(arr)) return;
          if (index < 0 || index >= arr.length) return;
          arr.splice(index, 1);
          syncHrfVariablesWithModelX();
          setModelEditorStatus('Regressor removed', 'info');
          renderModelAccordionEditor();
        }

        const trialPoolCard = document.createElement('div');
        trialPoolCard.className = 'border rounded p-2 mb-2 bg-light-subtle';
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
            ? 'No trial_type values detected for the current BIDS/task selection.'
            : 'Task-specific trial types are hidden while zero or multiple tasks are selected.';
          trialPool.appendChild(empty);
        } else {
          trialTypeRegressors.forEach(reg => {
            const badge = document.createElement('button');
            badge.type = 'button';
            badge.className = 'btn btn-sm btn-outline-primary modelx-reg-badge';
            badge.textContent = reg;
            badge.draggable = true;
            badge.addEventListener('click', ()=> addRegressorToModelX(basePath, reg));
            badge.addEventListener('dragstart', (event)=>{
              event.dataTransfer.effectAllowed = 'copy';
              event.dataTransfer.setData('application/x-modelx-regressor', reg);
              event.dataTransfer.setData('text/plain', reg);
            });
            trialPool.appendChild(badge);
          });
        }
        trialPoolCard.appendChild(trialPool);
        listWrap.appendChild(trialPoolCard);


        if (conditionRegressors.length) {
          const condPool = document.createElement('div');
          condPool.className = 'modelx-pool mb-2';
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
            badge.addEventListener('click', ()=> addRegressorToModelX(basePath, reg));
            badge.addEventListener('dragstart', (event)=>{
              event.dataTransfer.effectAllowed = 'copy';
              event.dataTransfer.setData('application/x-modelx-regressor', reg);
              event.dataTransfer.setData('text/plain', reg);
            });
            condPool.appendChild(badge);
          });
          listWrap.appendChild(condPool);
        }

        const nuisanceCard = document.createElement('div');
        nuisanceCard.className = 'border rounded p-2 mb-2 bg-white';
        const nuisanceTitle = document.createElement('div');
        nuisanceTitle.className = 'small fw-bold mb-1';
        nuisanceTitle.textContent = 'Regressors of No Interest (fMRIPrep confounds check)';
        nuisanceCard.appendChild(nuisanceTitle);

        const nuisanceHint = document.createElement('div');
        nuisanceHint.className = 'small text-muted mb-2';
        nuisanceHint.textContent = confoundColumns.length
          ? `Detected ${confoundColumns.length} confound columns. Drag or click badges into Design Matrix space.`
          : 'No confounds file detected yet. Set fMRIPrep folder to validate columns.';
        nuisanceCard.appendChild(nuisanceHint);

        const nuisanceInModelX = currentRegs.filter(isNuisanceRegressor);
        if (nuisanceInModelX.length) {
          const warning = document.createElement('div');
          warning.className = 'alert alert-warning py-1 small mb-2';
          warning.textContent = `${nuisanceInModelX.length} nuisance regressor(s) are currently inside Model.X.`;
          nuisanceCard.appendChild(warning);

          const removeNuisanceBtn = document.createElement('button');
          removeNuisanceBtn.type = 'button';
          removeNuisanceBtn.className = 'btn btn-sm btn-outline-danger mb-2';
          removeNuisanceBtn.textContent = 'Remove nuisance regressors from Model.X';
          removeNuisanceBtn.addEventListener('click', () => {
            const arr = getByPath(modelEditorDraft, basePath);
            if (!Array.isArray(arr)) return;
            const filtered = arr.filter(reg => !isNuisanceRegressor(reg));
            setByPath(modelEditorDraft, basePath, filtered);
            syncHrfVariablesWithModelX();
            setModelEditorStatus('Removed nuisance regressors from Model.X.', 'info');
            renderModelAccordionEditor();
          });
          nuisanceCard.appendChild(removeNuisanceBtn);
        }

        const nuisanceOptions = Array.from(new Set([
          ...defaultTransRot,
          'framewise_displacement',
          ...transRotConfounds
        ]));
        const nuisanceGrid = document.createElement('div');
        nuisanceGrid.className = 'modelx-pool';

        nuisanceOptions.forEach(reg => {
          const presentInConfounds = hasConfoundColumn(confoundColumns, reg) || transRotConfounds.includes(reg);
          const badge = document.createElement('button');
          badge.type = 'button';
          badge.className = presentInConfounds
            ? 'btn btn-sm btn-outline-secondary modelx-reg-badge'
            : 'btn btn-sm btn-outline-danger modelx-reg-badge';
          badge.textContent = presentInConfounds ? reg : `${reg} (missing)`;
          badge.draggable = true;
          badge.addEventListener('click', ()=> addRegressorToModelX(basePath, reg));
          badge.addEventListener('dragstart', (event)=>{
            event.dataTransfer.effectAllowed = 'copy';
            event.dataTransfer.setData('application/x-modelx-regressor', reg);
            event.dataTransfer.setData('text/plain', reg);
          });
          nuisanceGrid.appendChild(badge);
        });
        nuisanceCard.appendChild(nuisanceGrid);
        listWrap.appendChild(nuisanceCard);

        const dropZoneTitle = document.createElement('div');
        dropZoneTitle.className = 'small fw-bold mb-1';
        dropZoneTitle.textContent = 'Design Matrix space';
        listWrap.appendChild(dropZoneTitle);

        const dropZone = document.createElement('div');
        dropZone.className = 'modelx-drop-zone mb-2';
        const onDropAtIndex = (event, index) => {
          const sourceIndexRaw = event.dataTransfer.getData('application/x-modelx-index');
          const droppedValue = (event.dataTransfer.getData('application/x-modelx-regressor') || event.dataTransfer.getData('text/plain') || '').trim();
          if (sourceIndexRaw !== '') {
            const sourceIndex = Number(sourceIndexRaw);
            if (!Number.isNaN(sourceIndex)) {
              moveRegressorToIndex(basePath, sourceIndex, index);
              return;
            }
          }
          if (droppedValue) addRegressorToModelX(basePath, droppedValue, index);
        };

        dropZone.addEventListener('dragover', (event)=>{
          event.preventDefault();
          dropZone.classList.add('is-over');
        });
        dropZone.addEventListener('dragleave', ()=> dropZone.classList.remove('is-over'));
        dropZone.addEventListener('drop', (event)=>{
          event.preventDefault();
          dropZone.classList.remove('is-over');
          onDropAtIndex(event, currentRegs.length);
        });

        if (!currentRegs.length) {
          const empty = document.createElement('div');
          empty.className = 'small text-muted w-100';
          empty.textContent = 'Drop trial_type / nuisance badges here to build Model.X. Drag badges to reorder.';
          dropZone.appendChild(empty);
        } else {
          currentRegs.forEach((reg, idx) => {
            const chip = document.createElement('div');
            chip.className = 'modelx-chip';
            chip.draggable = true;
            chip.title = 'Drag to reorder';

            chip.addEventListener('dragstart', (event)=>{
              event.dataTransfer.effectAllowed = 'move';
              event.dataTransfer.setData('application/x-modelx-index', String(idx));
              event.dataTransfer.setData('application/x-modelx-regressor', String(reg));
              event.dataTransfer.setData('text/plain', String(reg));
            });
            chip.addEventListener('dragover', (event)=>{
              event.preventDefault();
              chip.classList.add('is-drop-target');
            });
            chip.addEventListener('dragleave', ()=> chip.classList.remove('is-drop-target'));
            chip.addEventListener('drop', (event)=>{
              event.preventDefault();
              event.stopPropagation();
              chip.classList.remove('is-drop-target');
              onDropAtIndex(event, idx);
            });
            chip.addEventListener('dragend', ()=> chip.classList.remove('is-drop-target'));

            const main = document.createElement('div');
            main.className = 'modelx-chip-main';

            const handle = document.createElement('span');
            handle.className = 'modelx-chip-handle';
            handle.innerHTML = '<i class="fas fa-grip-vertical"></i>';

            const label = document.createElement('span');
            label.className = isNuisanceRegressor(reg)
              ? 'badge text-bg-secondary modelx-chip-label'
              : 'badge bg-primary modelx-chip-label';
            label.textContent = reg;

            main.appendChild(handle);
            main.appendChild(label);

            const actions = document.createElement('div');
            actions.className = 'modelx-chip-actions';

            const hrfBtn = document.createElement('button');
            hrfBtn.type = 'button';
            hrfBtn.className = isRegressorHrfEnabled(reg)
              ? 'btn btn-sm btn-success'
              : 'btn btn-sm btn-outline-secondary';
            hrfBtn.textContent = isRegressorHrfEnabled(reg) ? 'HRF on' : 'HRF off';
            if (isHrfApplicableRegressor(reg)) {
              hrfBtn.addEventListener('click', (event)=>{
                event.stopPropagation();
                toggleRegressorHrf(reg);
              });
            } else {
              hrfBtn.disabled = true;
              hrfBtn.textContent = 'HRF n/a';
            }

            const delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.className = 'modelx-chip-remove';
            delBtn.title = 'Remove regressor';
            delBtn.innerHTML = '<i class="fas fa-times"></i>';
            delBtn.addEventListener('click', (event)=>{
              event.stopPropagation();
              removeModelXRegressor(idx);
            });

            actions.appendChild(hrfBtn);
            actions.appendChild(delBtn);
            chip.appendChild(main);
            chip.appendChild(actions);
            dropZone.appendChild(chip);
          });
        }
        listWrap.appendChild(dropZone);

        const advanced = document.createElement('details');
        advanced.className = 'mb-2';
        const advSummary = document.createElement('summary');
        advSummary.className = 'small fw-bold';
        advSummary.textContent = 'Add custom regressor (advanced)';
        advanced.appendChild(advSummary);

        const customRow = document.createElement('div');
        customRow.className = 'd-flex gap-2 mt-2';
        const customInput = document.createElement('input');
        customInput.type = 'text';
        customInput.className = 'form-control form-control-sm';
        customInput.placeholder = 'e.g. custom_modulator';
        const customBtn = document.createElement('button');
        customBtn.type = 'button';
        customBtn.className = 'btn btn-sm btn-outline-secondary';
        customBtn.textContent = 'Add';
        customBtn.addEventListener('click', ()=>{
          const value = (customInput.value || '').trim();
          if (!value) return;
          if (/\s/.test(value)) {
            setModelEditorStatus('Custom regressor names cannot contain spaces.', 'warning');
            return;
          }
          addRegressorToModelX(basePath, value);
        });
        customRow.appendChild(customInput);
        customRow.appendChild(customBtn);
        advanced.appendChild(customRow);
        listWrap.appendChild(advanced);

        const interceptBtn = document.createElement('button');
        interceptBtn.type = 'button';
        interceptBtn.className = 'btn btn-sm btn-outline-secondary';
        interceptBtn.textContent = 'Add intercept (1)';
        interceptBtn.addEventListener('click', ()=> addRegressorToModelX(basePath, '1', 0));
        listWrap.appendChild(interceptBtn);

        container.appendChild(listWrap);
        return;
      }

      if (/\.GroupBy$/.test(basePath)) { const controls = document.createElement('div'); controls.className='d-flex flex-wrap gap-2 align-items-center p-2 mb-2 border rounded bg-white'; const current = Array.isArray(node)?node:[]; const remaining = (modelEditorGroupByOptions||['subject']).filter(opt=>!current.includes(opt)); const select = document.createElement('select'); select.className='form-select form-select-sm'; select.style.maxWidth='260px'; const sourceOptions = remaining.length ? remaining : (modelEditorGroupByOptions || ['subject']); sourceOptions.forEach(optVal=>{ const opt=document.createElement('option'); opt.value=optVal; opt.textContent=optVal; select.appendChild(opt); }); controls.appendChild(select); const addBtn = document.createElement('button'); addBtn.type='button'; addBtn.className='btn btn-sm btn-outline-success'; addBtn.textContent='+ Add'; addBtn.disabled = remaining.length===0; addBtn.addEventListener('click', ()=>{ const value = select.value; const arr = getByPath(modelEditorDraft, basePath); if (!Array.isArray(arr)) return; if (arr.includes(value)) { const status = document.getElementById('model-editor-status'); status.innerHTML = `<div class="alert alert-warning py-1 x-small mb-2">GroupBy already selected: ${value}</div>`; return; } arr.push(value); renderModelAccordionEditor(); }); controls.appendChild(addBtn); listWrap.appendChild(controls); }
      node.forEach((item, idx) => { const itemPath = `${basePath}[${idx}]`; const locked = inheritedLocked || isReadonlyModelPath(itemPath); let displayLabel; if (item !== null && typeof item === 'object') displayLabel = item.Name || `#${idx+1}`; else displayLabel = item !== null && item !== '' ? String(item) : `#${idx+1}`; if (item !== null && typeof item === 'object') createBranchAccordion(listWrap, displayLabel, itemPath, item, locked, depth); else createPrimitiveRow(listWrap, `#${idx+1}`, item, itemPath, locked, depth); }); container.appendChild(listWrap); return; }
    if (node !== null && typeof node === 'object') {
      const objWrap = document.createElement('div');
      objWrap.className='accordion';
      let suppressedHrfVariables = false;

      Object.entries(node).forEach(([key, value])=>{
        if (/^Nodes\[\d+\]$/.test(basePath) && (key==='Level' || key==='Name')) return;
        if (/\.Model\.HRF$/.test(basePath) && key === 'Variables') {
          suppressedHrfVariables = true;
          return;
        }
        const path = basePath ? `${basePath}.${key}` : key;
        const locked = inheritedLocked || isReadonlyModelPath(path);
        if (value !== null && typeof value === 'object') createBranchAccordion(objWrap, key, path, value, locked, depth);
        else createPrimitiveRow(objWrap, key, value, path, locked, depth);
      });

      if (suppressedHrfVariables) {
        const hint = document.createElement('div');
        hint.className = 'small text-muted border rounded p-2 mb-2 bg-light-subtle';
        hint.textContent = 'HRF.Variables are controlled by the HRF on/off tags in Design Matrix space.';
        objWrap.appendChild(hint);
      }

      container.appendChild(objWrap);
      return;
    }
    createPrimitiveRow(container, basePath||'value', node, basePath||'value', inheritedLocked, depth);
  }

  function computeModelEditorSummary(model) { const sections = getModelEditorSections(model); const totals = sections.reduce((acc, section)=>{ acc.filled += section.stats.filled; acc.total += section.stats.total; return acc; }, { filled:0, total:0 }); return { score: totals.total>0 ? Math.round((totals.filled / totals.total)*100) : 0, filled: totals.filled, total: totals.total, sections }; }

  function renderModelEditorSummary(summary){ const summaryPanel = document.getElementById('model-editor-summary'); const progressBar = document.getElementById('model-editor-progress-bar'); const score = document.getElementById('model-editor-score'); const ring = document.getElementById('model-editor-score-ring'); const ringLabel = document.getElementById('model-editor-score-ring-label'); const sectionSummary = document.getElementById('model-editor-section-summary'); if (!summaryPanel || !progressBar || !score || !ring || !ringLabel || !sectionSummary) return; if (!summary) { summaryPanel.classList.add('d-none'); sectionSummary.innerHTML=''; return; } summaryPanel.classList.remove('d-none'); progressBar.style.width = `${summary.score}%`; score.textContent = `${summary.score}%`; ring.style.setProperty('--model-progress', String(summary.score)); ringLabel.textContent = `${summary.score}%`; sectionSummary.innerHTML=''; summary.sections.forEach(section=>{ const row = document.createElement('div'); row.className='model-section-summary-row'; const label = document.createElement('span'); label.className='section-label'; label.textContent = section.label; const dot = document.createElement('span'); dot.className = `completeness-dot ${section.stats.dotClass}`; dot.title = `${section.stats.filled}/${section.stats.total}`; const pills = document.createElement('div'); pills.className='model-meta-pills'; section.stats.badges.forEach(badge=>appendModelMetaPill(pills, badge.text, badge.tone)); row.appendChild(label); row.appendChild(dot); row.appendChild(pills); sectionSummary.appendChild(row); }); }

  function updateModelJsonPreview(){
    const preview = document.getElementById('model-json-preview');
    if (!preview) return;
    if (!modelEditorDraft || typeof modelEditorDraft !== 'object') {
      preview.textContent = 'Load a model to see the live JSON preview.';
      preview.classList.add('model-editor-preview-empty');
      setModelPreviewValidationState('idle', 'Load a model to run live schema validation.');
      return;
    }
    preview.textContent = JSON.stringify(modelEditorDraft, null, 2);
    preview.classList.remove('model-editor-preview-empty');
    scheduleModelPreviewValidation();
  }

  function setModelPreviewValidationState(state, message) {
    const badge = document.getElementById('model-preview-validation-badge');
    const text = document.getElementById('model-preview-validation-text');
    if (!badge || !text) return;

    const badgeMap = {
      idle: 'bg-secondary',
      checking: 'bg-info text-dark',
      valid: 'bg-success',
      invalid: 'bg-danger',
      error: 'bg-warning text-dark'
    };

    badge.className = `badge ${badgeMap[state] || 'bg-secondary'}`;
    badge.textContent = state;
    text.textContent = message;
  }

  function scheduleModelPreviewValidation() {
    if (previewValidationState.timer) clearTimeout(previewValidationState.timer);
    previewValidationState.timer = setTimeout(() => {
      validateModelPreviewLive();
    }, 250);
  }

  async function validateModelPreviewLive() {
    const runId = ++previewValidationState.runId;
    if (!modelEditorDraft || typeof modelEditorDraft !== 'object') {
      setModelPreviewValidationState('idle', 'Load a model to run live schema validation.');
      return;
    }

    const snapshot = structuredClone(modelEditorDraft);
    setModelPreviewValidationState('checking', 'Validating live JSON preview...');

    try {
      const response = await fetch('/validate_model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: snapshot })
      });

      const result = await response.json();
      if (runId !== previewValidationState.runId) return;

      if (result.valid) {
        if (result.warning) {
          setModelPreviewValidationState('valid', `Valid model (${result.warning})`);
        } else {
          setModelPreviewValidationState('valid', 'Valid BIDS Stats Model.');
        }
      } else {
        const msg = result.error ? String(result.error) : 'Schema validation failed.';
        setModelPreviewValidationState('invalid', msg);
      }
    } catch (err) {
      if (runId !== previewValidationState.runId) return;
      setModelPreviewValidationState('error', `Validation request failed: ${err.message}`);
    }
  }

  function renderModelAccordionEditor(){ const editor = document.getElementById('model-editor-accordion'); const status = document.getElementById('model-editor-status'); const openPaths = new Set(Array.from(editor.querySelectorAll('.accordion-collapse.show')).map(el=>el.dataset.jsonPath||'').filter(Boolean)); if (window.modelEditorPendingOpenPaths instanceof Set && window.modelEditorPendingOpenPaths.size) { window.modelEditorPendingOpenPaths.forEach(path=>openPaths.add(path)); window.modelEditorPendingOpenPaths.clear(); } modelEditorOpenPaths = openPaths; editor.innerHTML=''; if (!modelEditorDraft || typeof modelEditorDraft !== 'object') { renderModelEditorSummary(null); updateModelJsonPreview(); editor.innerHTML = '<div class="text-muted small">No model loaded.</div>'; return; } const missing = REQUIRED_ROOT_KEYS.filter(k => !(k in modelEditorDraft)); if (missing.length) { status.innerHTML = `<div class="alert alert-warning py-1 x-small mb-2">Missing required keys: ${missing.join(', ')}</div>`; } if (!Array.isArray(modelEditorDraft.Input?.task)) { if (!modelEditorDraft.Input || typeof modelEditorDraft.Input !== 'object') modelEditorDraft.Input = {}; modelEditorDraft.Input.task = []; } const summary = computeModelEditorSummary(modelEditorDraft); renderModelEditorSummary(summary);
  // Filter sections to display based on current left-pane selection
  const sel = window.currentSelection || { type: 'model' };
  let sectionsToRender = summary.sections;
  if (sel.type === 'modelField') {
    const overviewFields = new Set(['Name', 'BIDSModelVersion', 'Description']);
    const targetStatePath = overviewFields.has(sel.field) ? '__section_overview' : sel.field;
    const filtered = summary.sections.filter(s => s.id === targetStatePath || s.statePath === targetStatePath);
    if (filtered.length) {
      sectionsToRender = filtered;
      modelEditorOpenPaths.add(targetStatePath);
    }
  } else if (sel.type === 'nodeField') {
    const filtered = summary.sections.filter(s => s.id === 'Nodes');
    if (filtered.length) {
      sectionsToRender = filtered;
      const nodeIdx = Number(sel.idx);
      const nodePath = `Nodes[${nodeIdx}]`;
      modelEditorOpenPaths.add('Nodes');
      modelEditorOpenPaths.add(nodePath);
      if (sel.field) modelEditorOpenPaths.add(`${nodePath}.${sel.field}`);
    }
  }
  sectionsToRender.forEach(section => createModelSectionCard(editor, section)); updateModelJsonPreview(); }

  // expose saveModelEditor for the outer script
  async function saveModelEditor(){
    const modelPathVal = document.getElementById('model-path-input')?.value || '';
    const status = document.getElementById('model-editor-status');
    if (!modelPathVal) { if (status) status.innerHTML = '<div class="alert alert-danger py-1 x-small mb-0">Set model path first.</div>'; return; }
    if (!modelEditorDraft || typeof modelEditorDraft !== 'object') { if (status) status.innerHTML = '<div class="alert alert-danger py-1 x-small mb-0">No editable model loaded.</div>'; return; }
    const missing = REQUIRED_ROOT_KEYS.filter(k => !(k in modelEditorDraft));
    if (missing.length) { if (status) status.innerHTML = `<div class="alert alert-danger py-1 x-small mb-0">Missing required keys: ${missing.join(', ')}</div>`; return; }
    if (!Array.isArray(modelEditorDraft.Input?.task) || modelEditorDraft.Input.task.length === 0) { if (status) status.innerHTML = '<div class="alert alert-danger py-1 x-small mb-0">Select at least one Input.task.</div>'; return; }
    if (status) status.innerHTML = '<div class="text-muted x-small">Saving...</div>';
    try{
      const res = await fetch('/file_content', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ path: modelPathVal, content: JSON.stringify(modelEditorDraft, null, 2), validate_json: true }) });
      const result = await res.json();
      if (!result.success) { if (status) status.innerHTML = `<div class="alert alert-danger py-1 x-small mb-0">${result.error}</div>`; return; }
      if (status) status.innerHTML = '<div class="alert alert-success py-1 x-small mb-0">Model saved.</div>';
    } catch (e) { if (status) status.innerHTML = `<div class="alert alert-danger py-1 x-small mb-0">Save failed: ${e.message}</div>`; }
  }

  // attach small handlers
  document.getElementById('model-show-paths')?.addEventListener('change', (e)=>{ showModelTechnicalPaths = e.target.checked; renderModelAccordionEditor(); });

  // expose to outer scope
  window.renderModelAccordionEditor = renderModelAccordionEditor;
  window.saveModelEditor = saveModelEditor;
})();
