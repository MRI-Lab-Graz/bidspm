(function () {
  'use strict';

  function createTransformerBuilderPipeline(config) {
    const {
      getSelectableColumns,
      getColumnDomain,
      normalizeColumnList,
      renderColumnsPool,
      refreshPipelineColumnValues,
      scheduleLiveModelValidation,
      setStatus,
      escHtml,
      escAttr,
      getTargetLevels,
      normalizeNodeLevel,
      getOperationCategory,
      loadModelForValidation,
      getSelectedModelPath,
      requiredOutputOps,
      setSeedColumns,
    } = config || {};

    if (
      typeof getSelectableColumns !== 'function' ||
      typeof getColumnDomain !== 'function' ||
      typeof normalizeColumnList !== 'function' ||
      typeof renderColumnsPool !== 'function' ||
      typeof refreshPipelineColumnValues !== 'function' ||
      typeof scheduleLiveModelValidation !== 'function' ||
      typeof setStatus !== 'function' ||
      typeof escHtml !== 'function' ||
      typeof escAttr !== 'function' ||
      typeof getTargetLevels !== 'function' ||
      typeof normalizeNodeLevel !== 'function' ||
      typeof getOperationCategory !== 'function' ||
      typeof loadModelForValidation !== 'function' ||
      typeof getSelectedModelPath !== 'function' ||
      !(requiredOutputOps instanceof Set)
    ) {
      throw new Error('Transformer Builder pipeline dependencies are incomplete.');
    }

    let opCounter = 0;

    const pipelineRoot = document.getElementById('op-pipeline');
    if (pipelineRoot && !pipelineRoot.dataset.pipelineDelegateReady) {
      pipelineRoot.dataset.pipelineDelegateReady = '1';
      pipelineRoot.addEventListener('click', event => {
        const removeButton = event.target.closest('.chip-rm');
        if (!removeButton) return;
        event.stopPropagation();
        const chip = removeButton.closest('.col-chip');
        const zone = chip && chip.closest('.col-drop-zone');
        if (chip) chip.remove();
        if (zone && !zone.querySelectorAll('.col-chip').length) addDropHint(zone);
        updateGeneratedJSON();
      });
    }

    function setupDropZone(zone) {
      if (zone.dataset.dzReady) return;
      zone.dataset.dzReady = '1';

      zone.addEventListener('dragover', event => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
        zone.classList.add('drag-over');
      });

      zone.addEventListener('dragleave', event => {
        if (!zone.contains(event.relatedTarget)) zone.classList.remove('drag-over');
      });

      zone.addEventListener('drop', event => {
        event.preventDefault();
        zone.classList.remove('drag-over', 'ready');
        const column = event.dataTransfer.getData('text/plain');
        if (column) assignColToZone(zone, column);
      });

      zone.addEventListener('click', event => {
        if (event.target.classList.contains('chip-rm') || event.target.closest('.chip-rm')) return;
        openColPicker(zone);
      });
    }

    function assignColToZone(zone, column) {
      const existing = getZoneValue(zone);
      if (zone.dataset.mode === 'multi') {
        if (!existing.includes(column)) setZoneValue(zone, [...existing, column]);
      } else {
        setZoneValue(zone, [column]);
      }
      updateGeneratedJSON();
    }

    function getZoneValue(zone) {
      return Array.from(zone.querySelectorAll('.col-chip')).map(chip => chip.dataset.col);
    }

    function setZoneValue(zone, columns) {
      zone.querySelectorAll('.col-chip, .drop-hint').forEach(element => element.remove());

      columns.forEach(column => {
        const chip = document.createElement('span');
        chip.className = 'col-chip';
        chip.dataset.col = column;
        chip.innerHTML = `<i class="fas fa-columns" style="font-size:.6rem;"></i> ${escHtml(column)} <button class="chip-rm" title="Remove">×</button>`;
        zone.appendChild(chip);
      });

      if (!columns.length) addDropHint(zone);
    }

    function addDropHint(zone) {
      const hint = document.createElement('span');
      hint.className = 'drop-hint';
      hint.textContent = zone.dataset.mode === 'multi'
        ? 'Drop columns here — or click to pick'
        : 'Drop column here — or click to pick';
      zone.appendChild(hint);
    }

    function openColPicker(zone) {
      document.querySelectorAll('.col-picker-popup').forEach(popup => popup.remove());
      const selectableColumns = getSelectableColumns();
      if (!selectableColumns.length) return;

      const popup = document.createElement('div');
      popup.className = 'col-picker-popup';

      selectableColumns.forEach(columnInfo => {
        const column = columnInfo.name;
        const item = document.createElement('div');
        item.className = 'col-picker-item';
        item.innerHTML = columnInfo.generated
          ? `${escHtml(column)} <span class="col-badge-note">generated</span>`
          : escHtml(column);
        item.addEventListener('mousedown', event => {
          event.preventDefault();
          assignColToZone(zone, column);
          popup.remove();
        });
        popup.appendChild(item);
      });

      document.body.appendChild(popup);
      const rect = zone.getBoundingClientRect();
      popup.style.top = `${rect.bottom + 4}px`;
      popup.style.left = `${rect.left}px`;
      const popupWidth = popup.offsetWidth;
      const windowWidth = window.innerWidth;
      if (rect.left + popupWidth > windowWidth - 8) {
        popup.style.left = `${windowWidth - popupWidth - 8}px`;
      }

      const close = event => {
        if (!popup.contains(event.target)) {
          popup.remove();
          document.removeEventListener('mousedown', close);
        }
      };
      setTimeout(() => document.addEventListener('mousedown', close), 50);
    }

    function addOperation(opType, category) {
      const pipeline = document.getElementById('op-pipeline');
      const emptyHint = document.getElementById('pipeline-empty-hint');
      if (emptyHint) emptyHint.remove();

      opCounter += 1;
      const id = `op-${opCounter}`;

      const card = document.createElement('div');
      card.className = `op-card ${category}-card`;
      card.id = id;
      card.dataset.opType = opType;
      card.dataset.cat = category;
      card.innerHTML = `
        <div class="op-card-header">
          <span class="op-type-badge ${category}">${category === 'munge' ? 'Munge' : 'Compute'}</span>
          <span class="op-card-title">${escHtml(opType)}</span>
          <button class="btn-op-remove" title="Remove">×</button>
        </div>
        <div class="op-card-body">${getOpFieldsHTML(opType, id)}</div>
      `;

      card.querySelector('.btn-op-remove').addEventListener('click', () => {
        card.remove();
        if (!document.querySelector('#op-pipeline .op-card')) {
          const hint = document.createElement('div');
          hint.id = 'pipeline-empty-hint';
          hint.className = 'empty-pipeline-hint';
          hint.innerHTML = '<i class="fas fa-plus-circle d-block mb-2" style="font-size:1.6rem;opacity:.4;"></i>Click an operation above to add it.<br>Drag columns from the left into the input fields.';
          pipeline.appendChild(hint);
        }
        updateGeneratedJSON();
      });

      pipeline.appendChild(card);

      card.querySelectorAll('.col-drop-zone').forEach(zone => {
        addDropHint(zone);
        setupDropZone(zone);
      });

      card.querySelectorAll('input:not([type="checkbox"]), textarea').forEach(element => {
        element.addEventListener('input', updateGeneratedJSON);
      });
      card.querySelectorAll('input[type="checkbox"]').forEach(element => {
        element.addEventListener('change', updateGeneratedJSON);
      });

      const addRowButton = card.querySelector('.btn-add-row');
      if (addRowButton) {
        addRowButton.addEventListener('click', () => addReplaceRow(card));
        card.querySelectorAll('.btn-rm-row').forEach(button => wireRmRow(button));
      }

      updateGeneratedJSON();
      return card;
    }

    function clearPipelineCards() {
      const pipeline = document.getElementById('op-pipeline');
      pipeline.querySelectorAll('.op-card').forEach(card => card.remove());
      if (!pipeline.querySelector('.op-card')) {
        const hint = document.createElement('div');
        hint.id = 'pipeline-empty-hint';
        hint.className = 'empty-pipeline-hint';
        hint.innerHTML = '<i class="fas fa-plus-circle d-block mb-2" style="font-size:1.6rem;opacity:.4;"></i>Click an operation above to add it.<br>Drag columns from the left into the input fields.';
        pipeline.appendChild(hint);
      }
      if (typeof setSeedColumns === 'function') setSeedColumns([]);
    }

    function setCardFieldValue(card, fieldName, value) {
      const input = card.querySelector(`input[data-field="${fieldName}"], textarea[data-field="${fieldName}"]`);
      if (!input) return;
      if (input.type === 'checkbox') {
        input.checked = Boolean(value);
        return;
      }
      if (Array.isArray(value)) {
        input.value = value.map(item => String(item || '').trim()).filter(Boolean).join(', ');
        return;
      }
      input.value = value === undefined || value === null ? '' : String(value);
    }

    function setCardZoneValue(card, fieldName, value) {
      const zone = card.querySelector(`.col-drop-zone[data-field="${fieldName}"]`);
      if (!zone) return;
      setZoneValue(zone, normalizeColumnList(value));
    }

    function populateReplaceRows(card, replacements) {
      const tbody = card.querySelector('.replace-table tbody');
      if (!tbody) return;
      tbody.innerHTML = '';
      (Array.isArray(replacements) ? replacements : []).forEach(rule => {
        const row = document.createElement('tr');
        row.innerHTML = `
          <td><input type="text" placeholder="old_value"></td>
          <td><input type="text" placeholder="new_value"></td>
          <td><button class="btn btn-sm btn-link text-danger p-0 btn-rm-row" title="Remove">×</button></td>
        `;
        const [keyInput, valueInput] = row.querySelectorAll('input');
        keyInput.value = String(rule?.key || '').trim();
        valueInput.value = String(rule?.value || '').trim();
        row.querySelectorAll('input').forEach(input => input.addEventListener('input', updateGeneratedJSON));
        wireRmRow(row.querySelector('.btn-rm-row'));
        tbody.appendChild(row);
      });
      if (!tbody.children.length) addReplaceRow(card);
    }

    function populateCardFromInstruction(card, instruction) {
      if (!card || !instruction || typeof instruction !== 'object') return;

      setCardZoneValue(card, 'Input', instruction.Input);
      setCardZoneValue(card, 'Target', instruction.Target);
      setCardZoneValue(card, 'By', instruction.By);

      if (card.dataset.opType === 'Threshold' && Object.prototype.hasOwnProperty.call(instruction, 'Threshold')) {
        if (instruction.Above === false) {
          setCardFieldValue(card, 'MaxThreshold', instruction.Threshold);
        } else {
          setCardFieldValue(card, 'MinThreshold', instruction.Threshold);
        }
      } else {
        setCardFieldValue(card, 'Output', instruction.Output);
      }

      ['Query', 'InputAttr', 'TargetAttr', 'Value', 'Weights'].forEach(fieldName => {
        if (Object.prototype.hasOwnProperty.call(instruction, fieldName)) {
          setCardFieldValue(card, fieldName, instruction[fieldName]);
        }
      });

      ['Cumulative', 'Demean', 'Rescale', 'OmitNan', 'Binarize', 'Signed'].forEach(fieldName => {
        const checkbox = card.querySelector(`input[type="checkbox"][data-field="${fieldName}"]`);
        if (!checkbox) return;
        if (Object.prototype.hasOwnProperty.call(instruction, fieldName)) {
          checkbox.checked = Boolean(instruction[fieldName]);
        }
      });

      if (card.dataset.opType === 'Replace') {
        populateReplaceRows(card, instruction.Replace);
      }
    }

    function findSeedTransformations(model) {
      const nodes = Array.isArray(model?.Nodes) ? model.Nodes : [];
      const targetLevels = new Set(getTargetLevels().map(level => normalizeNodeLevel(level)).filter(Boolean));
      const preferredNodes = nodes.filter(node => {
        if (!node || typeof node !== 'object') return false;
        const level = normalizeNodeLevel(node.Level);
        return targetLevels.size ? targetLevels.has(level) : true;
      });
      const nodesToInspect = preferredNodes.length ? preferredNodes : nodes;

      for (const node of nodesToInspect) {
        const transformations = (node?.Transformations && typeof node.Transformations === 'object' && !Array.isArray(node.Transformations))
          ? node.Transformations
          : null;
        const instructions = Array.isArray(transformations?.Instructions)
          ? transformations.Instructions.filter(item => item && typeof item === 'object')
          : [];
        if (instructions.length) {
          return {
            nodeName: String(node?.Name || '').trim(),
            nodeLevel: normalizeNodeLevel(node?.Level),
            instructions,
            generatedColumns: Array.isArray(transformations?.GeneratedColumns) ? transformations.GeneratedColumns : [],
          };
        }
      }

      return null;
    }

    async function maybeBootstrapPipelineFromModel(force = false, launchContext = null) {
      if (!force && document.querySelector('#op-pipeline .op-card')) return false;

      let model = null;
      if (launchContext?.modelSnapshot && typeof launchContext.modelSnapshot === 'object' && !Array.isArray(launchContext.modelSnapshot)) {
        model = structuredClone(launchContext.modelSnapshot);
      } else {
        const selectedModelPath = getSelectedModelPath();
        if (!selectedModelPath) return false;
        try {
          model = await loadModelForValidation(selectedModelPath);
        } catch (error) {
          return false;
        }
      }

      const seed = findSeedTransformations(model);
      if (!seed || !seed.instructions.length) return false;

      clearPipelineCards();

      seed.instructions.forEach(instruction => {
        const opType = String(instruction?.Name || '').trim();
        const category = getOperationCategory(opType);
        if (!category) return;
        const card = addOperation(opType, category);
        populateCardFromInstruction(card, instruction);
      });

      if (typeof setSeedColumns === 'function') {
        const seeded = seed.generatedColumns
          .filter(col => typeof col === 'string' && col.trim())
          .map(col => ({ name: col.trim() }));
        setSeedColumns(seeded);
      }

      updateGeneratedJSON();

      const nodeLabel = seed.nodeName
        ? `${seed.nodeLevel || 'node'} ${seed.nodeName}`
        : (seed.nodeLevel || 'selected node');
      setStatus(`Loaded ${seed.instructions.length} existing transformer instruction(s) from ${nodeLabel}.`, 'success');
      return true;
    }

    function getOpFieldsHTML(opType, id) {
      switch (opType) {
        case 'Assign': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
          </div>
          <div>
            <div class="op-field-label">Target Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Target" data-mode="multi"></div>
            <div class="op-field-hint">Input and Target are mapped 1-to-1 in order.</div>
          </div>
          <div class="row g-2">
            <div class="col-md-6">
              <div class="op-field-label">InputAttr <span class="text-muted fw-normal">(optional)</span></div>
              <input type="text" class="form-control form-control-sm" data-field="InputAttr" placeholder="value">
            </div>
            <div class="col-md-6">
              <div class="op-field-label">TargetAttr <span class="text-muted fw-normal">(optional)</span></div>
              <input type="text" class="form-control form-control-sm" data-field="TargetAttr" placeholder="value">
            </div>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="assigned_col1, assigned_col2">
          </div>`;
        case 'Filter': return `
          <div>
            <div class="op-field-label">Input <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="single"></div>
            <div class="op-field-hint">Column whose rows will be filtered.</div>
          </div>
          <div>
            <div class="op-field-label">Query <span class="text-danger">*</span>
              <span class="text-muted fw-normal ms-1" style="font-size:.68rem;">e.g. <code>trial_type == 'go'</code> or <code>trial_type==^(a|b)$</code> for multiple values</span>
            </div>
            <input type="text" class="form-control form-control-sm" data-field="Query" placeholder="trial_type == 'value'">
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="filtered_col">
          </div>`;
        case 'Concatenate': return `
          <div>
            <div class="op-field-label">Input Columns <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
            <div class="op-field-hint">Drop multiple columns — they will be concatenated with <code>_</code>.</div>
          </div>
          <div>
            <div class="op-field-label">Output Name <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="e.g. trial_combined">
          </div>`;
        case 'Factor': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
            <div class="op-field-hint">Dummy-codes each column. Output names: <code>col_level</code>.</div>
          </div>`;
        case 'Replace': return `
          <div>
            <div class="op-field-label">Input <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="single"></div>
          </div>
          <div>
            <div class="op-field-label">Replacements <span class="text-danger">*</span>
              <span class="text-muted fw-normal ms-1" style="font-size:.68rem;">(regex supported in key)</span>
            </div>
            <table class="replace-table">
              <thead><tr><th>Old value (key)</th><th>New value</th><th></th></tr></thead>
              <tbody>
                <tr>
                  <td><input type="text" placeholder="old_value"></td>
                  <td><input type="text" placeholder="new_value"></td>
                  <td><button class="btn btn-sm btn-link text-danger p-0 btn-rm-row" title="Remove">×</button></td>
                </tr>
              </tbody>
            </table>
            <button class="btn-add-row">+ Add row</button>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="replaced_col">
          </div>`;
        case 'Copy': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
          </div>
          <div>
            <div class="op-field-label">Output Names <span class="text-danger">*</span>
              <span class="text-muted fw-normal ms-1" style="font-size:.68rem;">comma-separated, 1-to-1 with input</span>
            </div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="new_col1, new_col2">
          </div>`;
        case 'DropNA': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="clean_col1, clean_col2">
          </div>`;
        case 'Split': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
          </div>
          <div>
            <div class="op-field-label">By Column(s) <span class="text-muted fw-normal">(optional)</span></div>
            <div class="col-drop-zone" data-field="By" data-mode="multi"></div>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="split_col1, split_col2">
          </div>`;
        case 'LabelIdenticalRows': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
            <div class="op-field-hint">Default generated labels use the suffix <code>_label</code>.</div>
          </div>
          <div class="form-check mt-1">
            <input class="form-check-input" type="checkbox" data-field="Cumulative" id="${id}-cumulative">
            <label class="form-check-label small" for="${id}-cumulative">Cumulative labels</label>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="trial_type_label">
          </div>`;
        case 'MergeIdenticalRows': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
            <div class="op-field-hint">Merges consecutive identical rows for the selected column(s).</div>
          </div>`;
        case 'Constant': return `
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="constant_col">
          </div>
          <div>
            <div class="op-field-label">Value <span class="text-muted fw-normal">(optional)</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Value" placeholder="1">
          </div>`;
        case 'Product': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
          </div>
          <div class="form-check mt-1">
            <input class="form-check-input" type="checkbox" data-field="OmitNan" id="${id}-product-omitnan">
            <label class="form-check-label small" for="${id}-product-omitnan">Omit NaN</label>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="product_col">
          </div>`;
        case 'Select': return `
          <div>
            <div class="op-field-label">Columns to Keep <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
            <div class="op-field-hint">All other columns will be dropped from further analysis.</div>
          </div>`;
        case 'Delete': return `
          <div>
            <div class="op-field-label">Columns to Delete <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
          </div>`;
        case 'Scale': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
          </div>
          <div class="d-flex gap-3 mt-1">
            <div class="form-check">
              <input class="form-check-input" type="checkbox" data-field="Demean" id="${id}-demean" checked>
              <label class="form-check-label small" for="${id}-demean">Demean</label>
            </div>
            <div class="form-check">
              <input class="form-check-input" type="checkbox" data-field="Rescale" id="${id}-rescale" checked>
              <label class="form-check-label small" for="${id}-rescale">Rescale (÷ SD)</label>
            </div>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="scaled_col">
          </div>`;
        case 'Mean': return `
          <div>
            <div class="op-field-label">Input <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="single"></div>
          </div>
          <div class="form-check mt-1">
            <input class="form-check-input" type="checkbox" data-field="OmitNan" id="${id}-omitnan">
            <label class="form-check-label small" for="${id}-omitnan">Omit NaN</label>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="mean_col">
          </div>`;
        case 'Std': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
          </div>
          <div class="form-check mt-1">
            <input class="form-check-input" type="checkbox" data-field="OmitNan" id="${id}-std-omitnan">
            <label class="form-check-label small" for="${id}-std-omitnan">Omit NaN</label>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="std_col">
          </div>`;
        case 'Sum': return `
          <div>
            <div class="op-field-label">Input Column(s) <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="multi"></div>
          </div>
          <div>
            <div class="op-field-label">Weights <span class="text-muted fw-normal">(optional comma-separated)</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Weights" placeholder="1, 0.5, -1">
          </div>
          <div class="form-check mt-1">
            <input class="form-check-input" type="checkbox" data-field="OmitNan" id="${id}-sum-omitnan">
            <label class="form-check-label small" for="${id}-sum-omitnan">Omit NaN</label>
          </div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="sum_col">
          </div>`;
        case 'Threshold': return `
          <div>
            <div class="op-field-label">Input <span class="text-danger">*</span></div>
            <div class="col-drop-zone" data-field="Input" data-mode="single"></div>
          </div>
          <div class="row g-2">
            <div class="col-md-6">
              <div class="op-field-label">Min threshold <span class="text-muted fw-normal">(keep values >= min)</span></div>
              <input type="number" class="form-control form-control-sm" data-field="MinThreshold" step="any" placeholder="0.2">
            </div>
            <div class="col-md-6">
              <div class="op-field-label">Max threshold <span class="text-muted fw-normal">(keep values <= max)</span></div>
              <input type="number" class="form-control form-control-sm" data-field="MaxThreshold" step="any" placeholder="5">
            </div>
          </div>
          <div class="d-flex gap-3 mt-1">
            <div class="form-check">
              <input class="form-check-input" type="checkbox" data-field="Binarize" id="${id}-bin">
              <label class="form-check-label small" for="${id}-bin">Binarize</label>
            </div>
            <div class="form-check">
              <input class="form-check-input" type="checkbox" data-field="Signed" id="${id}-signed" checked>
              <label class="form-check-label small" for="${id}-signed">Signed threshold</label>
            </div>
          </div>
          <div class="op-field-hint">Tip: set both min and max for ranges like response_time between 0.2 and 5 seconds.</div>
          <div>
            <div class="op-field-label">Output <span class="text-danger">*</span></div>
            <input type="text" class="form-control form-control-sm" data-field="Output" placeholder="thresholded_col">
          </div>`;
        default:
          return '<div class="text-muted small">Unknown operation.</div>';
      }
    }

    function addReplaceRow(card) {
      const tbody = card.querySelector('.replace-table tbody');
      const row = document.createElement('tr');
      row.innerHTML = `
        <td><input type="text" placeholder="old_value"></td>
        <td><input type="text" placeholder="new_value"></td>
        <td><button class="btn btn-sm btn-link text-danger p-0 btn-rm-row" title="Remove">×</button></td>
      `;
      row.querySelectorAll('input').forEach(input => input.addEventListener('input', updateGeneratedJSON));
      wireRmRow(row.querySelector('.btn-rm-row'));
      tbody.appendChild(row);
      updateGeneratedJSON();
    }

    function wireRmRow(button) {
      button.addEventListener('click', () => {
        button.closest('tr').remove();
        updateGeneratedJSON();
      });
    }

    function getTransformerPayload() {
      const instructions = [];
      document.querySelectorAll('#op-pipeline .op-card').forEach(card => {
        const ops = extractOpsFromCard(card);
        if (ops.length) instructions.push(...ops);
      });
      return {
        Transformer: 'bidspm',
        Instructions: instructions,
      };
    }

    function updateGeneratedJSON() {
      clearRequiredOutputMarkers();
      const json = getTransformerPayload();
      const instructions = json.Instructions;
      refreshPipelineColumnValues();
      document.getElementById('json-output').textContent = JSON.stringify(json, null, 2);
      updateRegressorPreview(instructions);
      refreshAllValuePills();
      renderColumnsPool();
      scheduleLiveModelValidation();
    }

    function refreshAllValuePills() {
      document.querySelectorAll('#op-pipeline .op-card').forEach(card => {
        const opType = card.dataset.opType;
        if (opType === 'Filter') refreshFilterPills(card);
        if (opType === 'Replace') refreshReplaceSuggestions(card);
      });
    }

    function refreshFilterPills(card) {
      const inputZone = card.querySelector('.col-drop-zone[data-field="Input"]');
      const queryInput = card.querySelector('input[data-field="Query"]');
      if (!inputZone || !queryInput) return;

      const allCols = getSelectableColumns().map(c => c.name).sort();
      let container = card.querySelector('.val-pills-container');

      if (!allCols.length) {
        if (container) container.remove();
        return;
      }

      // Default query column to the Input column; preserve user selection across refreshes
      const inputColumn = getZoneValue(inputZone)[0];
      const prevCol = container ? container.dataset.queryCol : null;
      const selectedCol = (prevCol && allCols.includes(prevCol))
        ? prevCol
        : (inputColumn && allCols.includes(inputColumn) ? inputColumn : allCols[0]);

      if (!container) {
        container = document.createElement('div');
        container.className = 'val-pills-container';
        queryInput.closest('div').appendChild(container);
      }
      container.dataset.queryCol = selectedCol;

      container.innerHTML = `
        <div class="val-pills-hint">
          <i class="fas fa-hand-pointer me-1"></i>Click one or more values to build the query:
          <select class="query-col-select form-select form-select-sm d-inline-block ms-2"
                  style="width:auto;font-size:.75rem;padding:.15rem .5rem;">
            ${allCols.map(col =>
              `<option value="${escAttr(col)}"${col === selectedCol ? ' selected' : ''}>${escHtml(col)}</option>`
            ).join('')}
          </select>
        </div>
        <div class="val-pills"></div>
      `;

      const select = container.querySelector('.query-col-select');
      const pillsDiv = container.querySelector('.val-pills');

      // Builds a Query string the backend (bids.transformers Filter) can actually
      // execute. The backend only parses a single "col <op> value" clause, so two or
      // more selected values must be expressed as one anchored regex alternation
      // rather than several "|"-joined "col == val" clauses (which only the first
      // clause would ever be applied).
      function buildEqualityQuery(col, values) {
        if (!values.length) return '';
        if (values.length === 1) return `${col}=='${values[0]}'`;
        return `${col}==^(${values.join('|')})$`;
      }

      // Parses an existing Query string to figure out which values (if any) are
      // currently selected for the given column, so pills stay in sync when a card
      // is reloaded or the query was hand-edited.
      function getSelectedValuesForColumn(query, col, domainValues) {
        const selected = new Set();
        const trimmed = String(query || '').trim();
        const eqIndex = trimmed.indexOf('==');
        if (eqIndex === -1) return selected;

        const left = trimmed.slice(0, eqIndex).trim();
        if (left !== col) return selected;

        const right = trimmed.slice(eqIndex + 2).trim();

        if ((right.startsWith('\'') && right.endsWith('\'')) ||
            (right.startsWith('"') && right.endsWith('"'))) {
          selected.add(right.slice(1, -1));
          return selected;
        }

        const altMatch = right.match(/^\^\((.*)\)\$$/);
        if (altMatch) {
          altMatch[1].split('|').forEach(v => { if (v) selected.add(v); });
          return selected;
        }

        if (domainValues.includes(right)) selected.add(right);
        return selected;
      }

      function renderPills(col) {
        container.dataset.queryCol = col;
        const values = getColumnDomain(col);
        if (!values.length) {
          pillsDiv.innerHTML = '<span class="text-muted" style="font-size:.75rem;">No values for this column</span>';
          return;
        }

        const selectedValues = getSelectedValuesForColumn(queryInput.value, col, values);

        pillsDiv.innerHTML = values.map(value =>
          `<button class="val-pill${selectedValues.has(String(value)) ? ' active' : ''}" data-col="${escAttr(col)}" data-val="${escAttr(value)}">${escHtml(value)}</button>`
        ).join('');

        pillsDiv.querySelectorAll('.val-pill').forEach(pill => {
          pill.addEventListener('click', () => {
            pill.classList.toggle('active');
            const nowSelected = Array.from(pillsDiv.querySelectorAll('.val-pill.active'))
              .map(b => b.dataset.val);
            queryInput.value = buildEqualityQuery(col, nowSelected);
            updateGeneratedJSON();
          });
        });
      }

      select.addEventListener('change', () => renderPills(select.value));
      renderPills(selectedCol);
    }

    function refreshReplaceSuggestions(card) {
      const inputZone = card.querySelector('.col-drop-zone[data-field="Input"]');
      if (!inputZone) return;
      const columns = getZoneValue(inputZone);
      const column = columns[0];
      const values = column ? getColumnDomain(column) : [];

      let hint = card.querySelector('.replace-val-hint');
      if (!values.length) {
        if (hint) hint.remove();
        return;
      }

      if (!hint) {
        hint = document.createElement('div');
        hint.className = 'replace-val-hint val-pills-container';
        const addRowButton = card.querySelector('.btn-add-row');
        if (addRowButton) addRowButton.parentNode.insertBefore(hint, addRowButton);
      }
      hint.innerHTML = `
        <div class="val-pills-hint"><i class="fas fa-hand-pointer me-1"></i>Click to add as replacement row:</div>
        <div class="val-pills">${values.map(value =>
          `<button class="val-pill" data-val="${escAttr(value)}">${escHtml(value)}</button>`
        ).join('')}</div>
      `;
      hint.querySelectorAll('.val-pill').forEach(pill => {
        pill.addEventListener('click', () => {
          const tbody = card.querySelector('.replace-table tbody');
          let filled = false;
          tbody.querySelectorAll('tr').forEach(row => {
            const keyInput = row.querySelector('td:first-child input');
            if (!filled && keyInput && !keyInput.value.trim()) {
              keyInput.value = pill.dataset.val;
              filled = true;
            }
          });
          if (!filled) {
            addReplaceRow(card);
            const rows = tbody.querySelectorAll('tr');
            const lastKeyInput = rows[rows.length - 1].querySelector('td:first-child input');
            if (lastKeyInput) lastKeyInput.value = pill.dataset.val;
          }
          updateGeneratedJSON();
        });
      });
    }

    function parseCsvTokens(value) {
      return String(value || '')
        .split(',')
        .map(token => token.trim())
        .filter(Boolean);
    }

    function clearRequiredOutputMarkers() {
      document.querySelectorAll('#op-pipeline .op-card').forEach(card => card.classList.remove('op-missing-output'));
      document.querySelectorAll('#op-pipeline .op-card input[data-field="Output"]').forEach(input => input.classList.remove('is-invalid'));
    }

    function collectRequiredOutputIssues() {
      clearRequiredOutputMarkers();
      const issues = [];
      document.querySelectorAll('#op-pipeline .op-card').forEach((card, index) => {
        const opType = String(card.dataset.opType || '').trim();
        if (!requiredOutputOps.has(opType)) return;
        const outputInput = card.querySelector('input[data-field="Output"]');
        const outputTokens = parseCsvTokens(outputInput?.value || '');
        if (outputTokens.length) return;

        card.classList.add('op-missing-output');
        if (outputInput) outputInput.classList.add('is-invalid');
        issues.push(`Op ${index + 1} (${opType}) is missing Output.`);
      });
      return issues;
    }

    function parseNumericCsv(value) {
      return parseCsvTokens(value)
        .map(token => Number(token))
        .filter(number => Number.isFinite(number));
    }

    function normalizeThresholdBound(value) {
      return Number.isFinite(value) ? value : null;
    }

    function createThresholdInstruction(input, threshold, above, output = '', options = {}) {
      const { signed = true, binarize = false } = options;
      const op = {
        Name: 'Threshold',
        Input: input,
        Threshold: threshold,
        Above: above,
      };

      if (!signed) op.Signed = false;
      if (binarize) op.Binarize = true;

      const out = String(output || '').trim();
      if (out) op.Output = out;

      return op;
    }

    function buildThresholdOps(op, card) {
      const input = typeof op.Input === 'string' ? op.Input.trim() : '';
      if (!input) return [];

      const minBound = normalizeThresholdBound(op.MinThreshold);
      const maxBound = normalizeThresholdBound(op.MaxThreshold);
      if (minBound === null && maxBound === null) return [];

      const output = String(op.Output || '').trim();
      const signed = op.Signed !== false;
      const binarize = op.Binarize === true;

      if (minBound !== null && maxBound !== null) {
        if (output) {
          const tempOutput = `${output}__min_${card.id || 'tmp'}`;
          return [
            createThresholdInstruction(input, minBound, true, tempOutput, { signed, binarize: false }),
            createThresholdInstruction(tempOutput, maxBound, false, output, { signed, binarize }),
          ];
        }
        return [
          createThresholdInstruction(input, minBound, true, '', { signed, binarize: false }),
          createThresholdInstruction(input, maxBound, false, '', { signed, binarize: false }),
        ];
      }

      if (minBound !== null) {
        return [createThresholdInstruction(input, minBound, true, output, { signed, binarize })];
      }

      return [createThresholdInstruction(input, maxBound, false, output, { signed, binarize })];
    }

    function extractOpsFromCard(card) {
      const name = card.dataset.opType;
      const op = { Name: name };

      card.querySelectorAll('.col-drop-zone[data-field]').forEach(zone => {
        const columns = getZoneValue(zone);
        if (!columns.length) return;
        op[zone.dataset.field] = zone.dataset.mode === 'multi' ? columns : columns[0];
      });

      card.querySelectorAll('input[data-field]:not([type="checkbox"]), textarea[data-field]').forEach(element => {
        const value = element.value.trim();
        if (!value) return;
        const field = element.dataset.field;
        if (element.type === 'number') {
          op[field] = parseFloat(value);
        } else if (field === 'Output' && value.includes(',')) {
          op[field] = value.split(',').map(item => item.trim()).filter(Boolean);
        } else {
          op[field] = value;
        }
      });

      card.querySelectorAll('input[type="checkbox"][data-field]').forEach(element => {
        op[element.dataset.field] = element.checked;
      });

      const replaceTable = card.querySelector('.replace-table');
      if (replaceTable) {
        const rows = [];
        replaceTable.querySelectorAll('tbody tr').forEach(row => {
          const [keyInput, valueInput] = row.querySelectorAll('input');
          if (keyInput && keyInput.value.trim()) {
            rows.push({ key: keyInput.value.trim(), value: valueInput ? valueInput.value.trim() : '' });
          }
        });
        if (rows.length) op.Replace = rows;
      }

      if (name === 'Assign') {
        if (typeof op.Output === 'string' && op.Output.includes(',')) op.Output = parseCsvTokens(op.Output);
        if (typeof op.InputAttr === 'string' && op.InputAttr.includes(',')) op.InputAttr = parseCsvTokens(op.InputAttr);
        if (typeof op.TargetAttr === 'string' && op.TargetAttr.includes(',')) op.TargetAttr = parseCsvTokens(op.TargetAttr);
      }

      if (name === 'DropNA' || name === 'Std') {
        if (typeof op.Output === 'string' && op.Output.includes(',')) op.Output = parseCsvTokens(op.Output);
      }

      if (name === 'Sum' && typeof op.Weights === 'string') {
        const weights = parseNumericCsv(op.Weights);
        if (weights.length) op.Weights = weights;
        else delete op.Weights;
      }

      if (name === 'Constant' && typeof op.Value === 'string') {
        const maybeNumber = Number(op.Value);
        if (Number.isFinite(maybeNumber) && /^-?\d+(\.\d+)?([eE][-+]?\d+)?$/.test(op.Value.trim())) {
          op.Value = maybeNumber;
        }
      }

      if (name === 'Threshold') {
        return buildThresholdOps(op, card);
      }

      return Object.keys(op).length > 1 ? [op] : [];
    }

    function extractOp(card) {
      const ops = extractOpsFromCard(card);
      return ops.length ? ops[0] : null;
    }

    function updateRegressorPreview(instructions) {
      const preview = document.getElementById('regressor-preview');
      const chips = [];

      instructions.forEach(instruction => {
        if (instruction.Name === 'Concatenate' && instruction.Output) {
          chips.push(`${instruction.Output}.*`);
        } else if (instruction.Name === 'Factor') {
          const inputs = Array.isArray(instruction.Input) ? instruction.Input : (instruction.Input ? [instruction.Input] : []);
          inputs.forEach(input => chips.push(`${input}_*`));
        } else if (instruction.Name === 'Filter' && instruction.Output) {
          chips.push(instruction.Output);
        }
      });

      preview.innerHTML = chips.length
        ? chips.map(regressor => `<span class="regressor-chip">${escHtml(regressor)}</span>`).join('')
        : '<div class="text-muted small">Add operations to see regressors…</div>';
    }

    function copyJSON() {
      const text = document.getElementById('json-output').textContent;
      navigator.clipboard.writeText(text).then(() => setStatus('JSON copied to clipboard!', 'success'));
    }

    return Object.freeze({
      addOperation,
      collectRequiredOutputIssues,
      copyJSON,
      extractOp,
      extractOpsFromCard,
      getTransformerPayload,
      maybeBootstrapPipelineFromModel,
      updateGeneratedJSON,
    });
  }

  window.BIDSPMTransformerBuilderPipeline = createTransformerBuilderPipeline;
})();