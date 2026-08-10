// analysis_json_editor.js
// Extracted from templates/analysis.html — JSON model editor rendering functions.
// Relies on globals defined in analysis.html inline script as var/function:
//   modelEditorDraft, modelEditorOpenPaths, modelEditorPendingOpenPaths,
//   modelEditorConfoundColumns, modelEditorTransRotConfounds, modelEditorGroupByOptions,
//   modelEditorEventNumericColumns, modelEditorEventNumericSamples,
//   showModelTechnicalPaths, showModelAdvancedFields,
//   appendModelMetaPill, computeModelEditorSummary, renderModelEditorSummary,
//   isReadonlyModelPath, isManagedModelHrfVariablesPath, isModelXPath, isFilledModelValue,
//   addArrayItem, addRegressorToModelX, setByPath, getByPath, parsePrimitiveInput,
//   reorderArrayItem, moveModelXRegressorByStep, isModelXRegressorHrfEnabled,
//   isHrfApplicableRegressor, toggleModelXRegressorHrf, syncModelXHrfVariables,
//   isManagedModelHrfPath, isDuplicateModelXRegressor, normalizeModelHrfVariables,
//   updateModelJsonPreview, getBranchBadgeDescriptors, createAdvancedFieldsBadge,
//   getModelObjectFromModelXPath, getModelObjectPathFromModelXPath, getSuggestedRegressorsForModelXPath,
//   getEdgeSchemaAdvisories, getEdgeSchemaChecks, getHrfSchemaChecks, getDirectFieldCompletion,
//   getKnownEdgeFilterMetadataKeys, createNodeSchemaHint, createEdgeSchemaHint, createHrfSchemaHint,
//   createOptionsSchemaHint, createTopLevelSchemaHint, createModelSchemaHint, createContrastSchemaHint,
//   createTransformationsSchemaHint, createDummyContrastsSchemaHint.

var REQUIRED_ROOT_KEYS = ['Name', 'BIDSModelVersion', 'Input', 'Nodes'];
const READONLY_MODEL_PATHS = [
    /^BIDSModelVersion$/,
    /^Input\.task$/,
    /^Input\.task\[\d+\]$/,
    /^Nodes\[\d+\]\.Level$/,
    /^Nodes\[\d+\]\.Name$/
];

    function createPrimitiveRow(container, label, value, path, locked = false, depth = 0) {
        const row = document.createElement('div');
        row.className = `json-row d-flex align-items-center gap-2 json-row-depth-${Math.min(depth, 4)}`;

        const keyEl = document.createElement('span');
        keyEl.className = 'json-key fw-semibold';
        keyEl.textContent = label;
        row.appendChild(keyEl);

        const inputWrap = document.createElement('div');
        inputWrap.className = 'json-inline-value';

        const pathEl = document.createElement('div');
        pathEl.className = 'json-path mb-1';
        pathEl.textContent = path;
        pathEl.style.display = showModelTechnicalPaths ? 'block' : 'none';
        inputWrap.appendChild(pathEl);

        const isModelXEntry = isModelXPath(path);
        const isGroupByEntry = /\.GroupBy\[\d+\]$/.test(path);
        const modelXPathMatch = path.match(/^(.*)\[\d+\]$/);
        const modelXArrayPath = modelXPathMatch ? modelXPathMatch[1] : '';
        const scopedInterestRegressors = isModelXEntry ? getSuggestedRegressorsForModelXPath(modelXArrayPath) : [];
        const useInterestDropdown = isModelXEntry && typeof value === 'string' && !isNuisanceRegressor(value) && scopedInterestRegressors.length > 0;
        const isSerialCorrelationEntry = /\.Software\.SPM\.SerialCorrelation$/.test(path);

        if (isGroupByEntry) {
            row.classList.add('json-row-compact');
        }

        let input;
        if (isSerialCorrelationEntry) {
            input = document.createElement('select');
            input.className = 'form-select form-select-sm';

            const options = Array.from(new Set(['none', 'AR(1)', 'FAST', value]));
            options.forEach(optVal => {
                const opt = document.createElement('option');
                opt.value = optVal;
                opt.textContent = optVal;
                input.appendChild(opt);
            });
            input.value = String(value);
        } else if (isGroupByEntry) {
            input = document.createElement('select');
            input.className = 'form-select form-select-sm';

            const options = Array.from(new Set([...(modelEditorGroupByOptions || []), value]));
            options.forEach(optVal => {
                const opt = document.createElement('option');
                opt.value = optVal;
                opt.textContent = optVal;
                input.appendChild(opt);
            });
            input.value = String(value);
        } else if (useInterestDropdown) {
            input = document.createElement('select');
            input.className = 'form-select form-select-sm';
            const options = Array.from(new Set([value, ...scopedInterestRegressors]));
            options.forEach(optVal => {
                const opt = document.createElement('option');
                opt.value = optVal;
                opt.textContent = optVal;
                input.appendChild(opt);
            });
            input.value = value;
        } else if (typeof value === 'boolean') {
            input = document.createElement('select');
            input.className = 'form-select form-select-sm';
            input.innerHTML = '<option value="true">true</option><option value="false">false</option>';
            input.value = value ? 'true' : 'false';
        } else if (typeof value === 'number') {
            input = document.createElement('input');
            input.type = 'number';
            input.step = 'any';
            input.className = 'form-control form-control-sm font-monospace';
            input.value = String(value);
        } else {
            input = document.createElement('input');
            input.type = 'text';
            input.className = 'form-control form-control-sm font-monospace';
            input.value = value === null ? '' : String(value);
        }

        if (locked) {
            input.readOnly = true;
            input.disabled = true;
            input.classList.add('json-locked');
            input.title = 'Locked mandatory field';
        } else {
            input.addEventListener('change', (e) => {
                const current = getByPath(modelEditorDraft, path);
                const newValue = parsePrimitiveInput(e.target.value, current);

                if (isModelXEntry && isDuplicateModelXRegressor(path, newValue)) {
                    const status = document.getElementById('model-editor-status');
                    status.innerHTML = `<div class="alert alert-warning py-1 x-small mb-2">Regressor already selected: ${newValue}</div>`;
                    e.target.value = current;
                    return;
                }

                setByPath(modelEditorDraft, path, newValue);
                if (isModelXEntry) {
                    syncModelXHrfVariables(path);
                }
                renderModelAccordionEditor();
            });
        }

        inputWrap.appendChild(input);
        row.appendChild(inputWrap);

        if (locked) {
            const badge = document.createElement('span');
            badge.className = 'badge text-bg-light border';
            badge.textContent = 'Locked';
            row.appendChild(badge);
        } else if (isModelXEntry && isNuisanceRegressor(value)) {
            const badge = document.createElement('span');
            badge.className = 'badge text-bg-secondary';
            badge.textContent = 'Nuisance';
            row.appendChild(badge);
        } else if (useInterestDropdown) {
            const badge = document.createElement('span');
            badge.className = 'badge text-bg-success';
            badge.textContent = 'Interest';
            row.appendChild(badge);
        }

        if (isModelXEntry && !locked) {
            const match = path.match(/^(.*)\[(\d+)\]$/);
            if (match) {
                const arrayPath = match[1];
                const index = Number(match[2]);
                const currentArray = getByPath(modelEditorDraft, arrayPath);
                const regressor = String(value || '').trim();
                const hrfEnabled = isModelXRegressorHrfEnabled(path);

                row.classList.add('json-row-modelx');

                const dragHandle = document.createElement('span');
                dragHandle.className = 'modelx-drag-handle';
                dragHandle.title = 'Drag to reorder';
                dragHandle.innerHTML = '<span class="modelx-drag-dots" aria-hidden="true"></span>';
                dragHandle.draggable = true;
                dragHandle.addEventListener('dragstart', (event) => {
                    modelXDragState = { arrayPath, index };
                    event.dataTransfer.effectAllowed = 'move';
                    event.dataTransfer.setData('text/plain', String(index));
                    event.dataTransfer.setData('application/x-modelx-arraypath', arrayPath);
                    event.dataTransfer.setData('application/x-modelx-index', String(index));
                    row.classList.add('is-dragging');
                });
                dragHandle.addEventListener('dragend', () => {
                    modelXDragState = null;
                    row.classList.remove('is-dragging');
                    row.classList.remove('is-drop-target');
                });
                row.insertBefore(dragHandle, keyEl);

                row.addEventListener('dragover', (event) => {
                    const hasRowMove = Boolean(modelXDragState && modelXDragState.arrayPath === arrayPath);
                    const droppedRegressor = (event.dataTransfer.getData('application/x-modelx-regressor') || event.dataTransfer.getData('text/plain') || '').trim();
                    const hasExternalRegressor = Boolean(droppedRegressor);
                    if (!hasRowMove && !hasExternalRegressor) return;
                    event.preventDefault();
                    event.dataTransfer.dropEffect = hasRowMove ? 'move' : 'copy';
                    const rect = row.getBoundingClientRect();
                    const dropAfter = event.clientY > (rect.top + rect.height / 2);
                    row.dataset.dropAfter = dropAfter ? '1' : '0';
                    row.classList.add('is-drop-target');
                });
                row.addEventListener('dragleave', () => {
                    delete row.dataset.dropAfter;
                    row.classList.remove('is-drop-target');
                });
                row.addEventListener('drop', (event) => {
                    event.preventDefault();
                    const sourcePath = modelXDragState?.arrayPath || event.dataTransfer.getData('application/x-modelx-arraypath');
                    const sourceIndexRaw = modelXDragState ? String(modelXDragState.index) : event.dataTransfer.getData('application/x-modelx-index');
                    const droppedRegressor = (event.dataTransfer.getData('application/x-modelx-regressor') || event.dataTransfer.getData('text/plain') || '').trim();
                    const dropAfter = row.dataset.dropAfter === '1';
                    const targetIndex = dropAfter ? index + 1 : index;
                    delete row.dataset.dropAfter;
                    row.classList.remove('is-drop-target');
                    if (sourcePath === arrayPath && sourceIndexRaw !== '') {
                        const sourceIndex = Number(sourceIndexRaw);
                        if (Number.isNaN(sourceIndex)) return;

                        const moved = reorderArrayItem(arrayPath, sourceIndex, targetIndex);
                        if (!moved) return;

                        const status = document.getElementById('model-editor-status');
                        status.innerHTML = '<div class="alert alert-info py-1 x-small mb-2">Regressor order updated</div>';
                        modelXDragState = null;
                        renderModelAccordionEditor();
                        return;
                    }

                    if (droppedRegressor) {
                        addRegressorToModelX(arrayPath, droppedRegressor, targetIndex);
                    }
                });

                const actions = document.createElement('div');
                actions.className = 'json-row-actions json-row-actions-modelx';

                const upBtn = document.createElement('button');
                upBtn.type = 'button';
                upBtn.className = 'btn btn-sm btn-outline-secondary';
                upBtn.title = 'Move up';
                upBtn.innerHTML = '<i class="fas fa-arrow-up"></i>';
                upBtn.disabled = index === 0;
                upBtn.addEventListener('click', () => {
                    const moved = moveModelXRegressorByStep(arrayPath, index, -1);
                    if (!moved) return;
                    const status = document.getElementById('model-editor-status');
                    status.innerHTML = '<div class="alert alert-info py-1 x-small mb-2">Regressor order updated</div>';
                    renderModelAccordionEditor();
                });

                const downBtn = document.createElement('button');
                downBtn.type = 'button';
                downBtn.className = 'btn btn-sm btn-outline-secondary';
                downBtn.title = 'Move down';
                downBtn.innerHTML = '<i class="fas fa-arrow-down"></i>';
                downBtn.disabled = !Array.isArray(currentArray) || index >= currentArray.length - 1;
                downBtn.addEventListener('click', () => {
                    const moved = moveModelXRegressorByStep(arrayPath, index, 1);
                    if (!moved) return;
                    const status = document.getElementById('model-editor-status');
                    status.innerHTML = '<div class="alert alert-info py-1 x-small mb-2">Regressor order updated</div>';
                    renderModelAccordionEditor();
                });

                const hrfBtn = document.createElement('button');
                hrfBtn.type = 'button';
                hrfBtn.className = hrfEnabled
                    ? 'btn btn-sm btn-success'
                    : 'btn btn-sm btn-outline-secondary';
                if (isHrfApplicableRegressor(regressor)) {
                    hrfBtn.title = 'Toggle HRF for this regressor';
                    hrfBtn.textContent = hrfEnabled ? 'HRF on' : 'HRF off';
                    hrfBtn.addEventListener('click', () => toggleModelXRegressorHrf(path));
                } else {
                    hrfBtn.title = 'Intercept is not HRF-convolved';
                    hrfBtn.textContent = 'HRF n/a';
                    hrfBtn.disabled = true;
                }

                const delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.className = 'btn btn-sm btn-outline-danger';
                delBtn.title = 'Remove regressor';
                delBtn.innerHTML = '<i class="fas fa-times"></i>';
                delBtn.addEventListener('click', () => {
                    removeArrayItem(path);
                    renderModelAccordionEditor();
                });

                actions.appendChild(upBtn);
                actions.appendChild(downBtn);
                actions.appendChild(hrfBtn);
                actions.appendChild(delBtn);
                row.appendChild(actions);
            }
        }

        if (isGroupByEntry && !locked) {
            const actions = document.createElement('div');
            actions.className = 'json-row-actions';

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn btn-sm btn-outline-danger';
            removeBtn.title = 'Remove';
            removeBtn.innerHTML = '<i class="fas fa-trash"></i>';
            removeBtn.addEventListener('click', () => {
                removeArrayItem(path);
                renderModelAccordionEditor();
            });

            actions.appendChild(removeBtn);
            row.appendChild(actions);
        }

        // Generic delete for any other primitive array item (e.g. ConditionList, Weights)
        if (!isModelXEntry && !isGroupByEntry && !locked && /\[\d+\]$/.test(path)) {
            const actions = document.createElement('div');
            actions.className = 'json-row-actions';

            const delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.className = 'btn btn-sm btn-outline-danger';
            delBtn.title = 'Remove';
            delBtn.innerHTML = '<i class="fas fa-times"></i>';
            delBtn.addEventListener('click', () => {
                removeArrayItem(path);
                renderModelAccordionEditor();
            });

            actions.appendChild(delBtn);
            row.appendChild(actions);
        }

        container.appendChild(row);
    }

    function createBranchAccordion(container, label, childPath, childValue, inheritedLocked, depth = 0) {
        const item = document.createElement('div');
        item.className = `accordion-item border-0 mb-2 json-depth-${Math.min(depth, 4)}`;

        const idBase = `json-${childPath.replace(/[^a-zA-Z0-9]/g, '-')}`;
        const headerId = `${idBase}-h`;
        const collapseId = `${idBase}-c`;

        const h2 = document.createElement('h2');
        h2.className = 'accordion-header';
        h2.id = headerId;

        const headerWrap = document.createElement('div');
        headerWrap.className = 'd-flex align-items-center gap-2';

        const btn = document.createElement('button');
        btn.className = 'accordion-button py-2 flex-grow-1'; // class set below after openIds check
        btn.type = 'button';
        btn.setAttribute('data-bs-toggle', 'collapse');
        btn.setAttribute('data-bs-target', `#${collapseId}`);
        btn.setAttribute('aria-expanded', 'false'); // overridden below
        btn.setAttribute('aria-controls', collapseId);
        const count = Array.isArray(childValue) ? childValue.length : Object.keys(childValue || {}).length;
        let displayLabel = label;
        if (/^Nodes\[\d+\]$/.test(childPath) && childValue && typeof childValue === 'object') {
            const lvl = childValue.Level || 'Run';
            const nm = childValue.Name || 'node';
            displayLabel = `${lvl} - ${nm}`;
        }
        const heading = document.createElement('span');
        heading.className = 'model-branch-heading';

        const labelEl = document.createElement('span');
        labelEl.className = 'model-branch-label';
        labelEl.textContent = displayLabel;
        heading.appendChild(labelEl);

        if (showModelTechnicalPaths) {
            const pathEl = document.createElement('span');
            pathEl.className = 'model-branch-path';
            pathEl.textContent = childPath;
            heading.appendChild(pathEl);
        }

        const meta = document.createElement('span');
        meta.className = 'model-branch-meta';
        getBranchBadgeDescriptors(childPath, childValue).forEach(badge => appendModelMetaPill(meta, badge.text, badge.tone));
        if (!meta.childNodes.length) {
            appendModelMetaPill(meta, `${count} ${Array.isArray(childValue) ? 'items' : 'fields'}`, 'neutral');
        }

        btn.appendChild(heading);
        btn.appendChild(meta);
        headerWrap.appendChild(btn);

        const isModelXArray = /\.Model\.X$/.test(childPath);
        const isGroupByArray = /\.GroupBy$/.test(childPath);
        if (Array.isArray(childValue) && !inheritedLocked && !isModelXArray && !isGroupByArray) {
            const addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'btn btn-sm btn-outline-success json-add-btn';
            addBtn.textContent = '+ Add';
            addBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                addArrayItem(childPath);
                renderModelAccordionEditor();
            });
            headerWrap.appendChild(addBtn);
        }

        // Delete button for array-element branch nodes (e.g. individual contrasts, nodes)
        if (!inheritedLocked && /\[\d+\]$/.test(childPath)) {
            const delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.className = 'btn btn-sm btn-outline-danger json-add-btn';
            delBtn.title = 'Delete';
            delBtn.innerHTML = '<i class="fas fa-times"></i>';
            delBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                removeArrayItem(childPath);
                renderModelAccordionEditor();
            });
            headerWrap.appendChild(delBtn);
        }

        h2.appendChild(headerWrap);

        const collapse = document.createElement('div');
        collapse.id = collapseId;
        collapse.dataset.jsonPath = childPath;
        // Restore open state if it was open before re-render; default stays collapsed.
        const wasOpen = modelEditorOpenPaths.has(childPath);
        collapse.className = `accordion-collapse collapse ${wasOpen ? 'show' : ''}`;
        btn.className = `accordion-button ${wasOpen ? '' : 'collapsed'} py-2 flex-grow-1`;
        btn.setAttribute('aria-expanded', wasOpen ? 'true' : 'false');
        collapse.setAttribute('aria-labelledby', headerId);

        const body = document.createElement('div');
        body.className = 'accordion-body py-2';
        renderJsonEditor(body, childValue, childPath, inheritedLocked, depth + 1);
        collapse.appendChild(body);

        item.appendChild(h2);
        item.appendChild(collapse);
        container.appendChild(item);
    }

    function renderJsonEditor(container, node, basePath = '', inheritedLocked = false, depth = 0) {
        if (Array.isArray(node)) {
            if (isManagedModelHrfVariablesPath(basePath)) {
                container.appendChild(createInlineNote('HRF variables are managed from Design Matrix rows (HRF on/off).'));
                return;
            }

            const listWrap = document.createElement('div');
            listWrap.className = 'accordion';

            const contrastPathMatch = String(basePath).match(/^Nodes\[(\d+)\]\.Contrasts$/);
            if (contrastPathMatch) {
                const nodeIdx = Number(contrastPathMatch[1]);
                const controls = document.createElement('div');
                controls.className = 'd-flex flex-wrap gap-2 align-items-center p-2 mb-2 border rounded bg-white';

                const hint = document.createElement('span');
                hint.className = 'small text-muted me-auto';
                hint.textContent = 'Use Contrast Builder for user-friendly contrast editing.';

                const openBtn = document.createElement('button');
                openBtn.type = 'button';
                openBtn.className = 'btn btn-sm btn-outline-primary';
                openBtn.innerHTML = '<i class="fas fa-puzzle-piece me-1"></i>Open Contrast Builder';
                openBtn.addEventListener('click', () => {
                    if (typeof window.openContrastBuilder === 'function') {
                        window.openContrastBuilder(nodeIdx);
                    } else {
                        alert('Contrast Builder not ready — please wait for the page to finish loading.');
                    }
                });

                controls.appendChild(hint);
                controls.appendChild(openBtn);
                listWrap.appendChild(controls);
            }

            if (/\.Model\.X$/.test(basePath)) {
                const controls = document.createElement('div');
                controls.className = 'd-flex flex-wrap gap-2 align-items-center p-2 mb-2 border rounded bg-white';

                const select = document.createElement('select');
                select.className = 'form-select form-select-sm';
                select.style.maxWidth = '340px';

                const uniqueRegs = getSuggestedRegressorsForModelXPath(basePath);
                const pathMatch = String(basePath).match(/^Nodes\[(\d+)\]\.Model\.X$/);
                const nodeIdx = pathMatch ? Number(pathMatch[1]) : -1;
                const nodeForPath = pathMatch && Array.isArray(modelEditorDraft?.Nodes)
                    ? modelEditorDraft.Nodes[nodeIdx]
                    : null;
                const isDatasetModelX = String(nodeForPath?.Level || '').trim().toLowerCase() === 'dataset';
                const isFirstLevelModelX = nodeIdx === 0;
                const isRunModelX = isFirstLevelModelX && String(nodeForPath?.Level || '').trim().toLowerCase() === 'run';
                const transformerRegressors = getTransformerModelXRegressorsForNode(nodeForPath);
                const hasTransformerPipeline = Boolean(nodeForPath?.Transformations && typeof nodeForPath.Transformations === 'object' && !Array.isArray(nodeForPath.Transformations));
                const modelPathForX = String(basePath || '').replace(/\.X$/, '');

                function getModelForCurrentX() {
                    const modelObj = getByPath(modelEditorDraft, modelPathForX);
                    if (!modelObj || typeof modelObj !== 'object' || Array.isArray(modelObj)) return null;
                    return modelObj;
                }

                function getConditionRegressorsForModulation() {
                    const regs = getByPath(modelEditorDraft, basePath);
                    // Condition regressors use "column.level" dot notation (trial_type.*,
                    // condition.*, or any Transformations-derived name like valid_item.item).
                    // Confound/motion regressors (trans_*, rot_*, motion_outlier*, "1", ...)
                    // never contain a dot, so this also excludes them without an allowlist.
                    return normalizeStringArray(regs).filter(reg => reg.includes('.'));
                }

                function getNumericColumnsForModulation() {
                    return normalizeStringArray(modelEditorEventNumericColumns);
                }

                function getNumericSamplesForColumn(columnName) {
                    if (!modelEditorEventNumericSamples || typeof modelEditorEventNumericSamples !== 'object') return [];
                    return normalizeStringArray(modelEditorEventNumericSamples[String(columnName || '').trim()]);
                }

                function normalizeParametricModulationEntry(entry, fallbackCondition = '', fallbackValue = '', index = 0) {
                    const conditions = normalizeStringArray(entry?.Conditions);
                    const values = normalizeStringArray(entry?.Values);
                    const rawPoly = Number(entry?.PolynomialExpansion);
                    return {
                        Name: String(entry?.Name || `parametric_mod_${index + 1}`).trim() || `parametric_mod_${index + 1}`,
                        Conditions: conditions.length ? conditions : (fallbackCondition ? [fallbackCondition] : []),
                        Values: values.length ? values : (fallbackValue ? [fallbackValue] : []),
                        PolynomialExpansion: Number.isFinite(rawPoly) && rawPoly > 0 ? Math.round(rawPoly) : 1
                    };
                }

                function getParametricModulationsForCurrentX() {
                    const modelObj = getModelForCurrentX();
                    const existing = modelObj?.Software?.SPM?.ParametricModulations;
                    if (!Array.isArray(existing)) return [];
                    const fallbackCondition = getConditionRegressorsForModulation()[0] || '';
                    const fallbackValue = getNumericColumnsForModulation()[0] || '';
                    return existing.map((entry, index) =>
                        normalizeParametricModulationEntry(entry, fallbackCondition, fallbackValue, index)
                    );
                }

                function setParametricModulationsForCurrentX(nextEntries) {
                    const modelObj = getModelForCurrentX();
                    if (!modelObj) return;

                    const normalizedEntries = Array.isArray(nextEntries)
                        ? nextEntries.map((entry, index) => normalizeParametricModulationEntry(entry, '', '', index))
                        : [];

                    if (!normalizedEntries.length) {
                        if (modelObj.Software && typeof modelObj.Software === 'object' && !Array.isArray(modelObj.Software)) {
                            if (modelObj.Software.SPM && typeof modelObj.Software.SPM === 'object' && !Array.isArray(modelObj.Software.SPM)) {
                                delete modelObj.Software.SPM.ParametricModulations;
                                if (!Object.keys(modelObj.Software.SPM).length) delete modelObj.Software.SPM;
                            }
                            if (!Object.keys(modelObj.Software).length) delete modelObj.Software;
                        }
                        return;
                    }

                    if (!modelObj.Software || typeof modelObj.Software !== 'object' || Array.isArray(modelObj.Software)) {
                        modelObj.Software = {};
                    }
                    if (!modelObj.Software.SPM || typeof modelObj.Software.SPM !== 'object' || Array.isArray(modelObj.Software.SPM)) {
                        modelObj.Software.SPM = {};
                    }
                    modelObj.Software.SPM.ParametricModulations = normalizedEntries;
                }

                if (uniqueRegs.length === 0) {
                    const opt = document.createElement('option');
                    opt.value = '';
                    opt.textContent = isDatasetModelX
                        ? 'No participants.tsv variables detected'
                        : 'No event regressors detected';
                    select.appendChild(opt);
                } else {
                    uniqueRegs.forEach(reg => {
                        const opt = document.createElement('option');
                        opt.value = reg;
                        opt.textContent = reg;
                        select.appendChild(opt);
                    });
                }
                controls.appendChild(select);

                const addBtn = document.createElement('button');
                addBtn.type = 'button';
                addBtn.className = 'btn btn-sm btn-outline-success';
                addBtn.textContent = '+ Add regressor';
                addBtn.disabled = uniqueRegs.length === 0;
                addBtn.addEventListener('click', () => addRegressorToModelX(basePath, select.value));
                controls.appendChild(addBtn);

                const customInput = document.createElement('input');
                customInput.type = 'text';
                customInput.className = 'form-control form-control-sm';
                customInput.placeholder = 'Custom regressor';
                customInput.style.maxWidth = '240px';
                controls.appendChild(customInput);

                const customBtn = document.createElement('button');
                customBtn.type = 'button';
                customBtn.className = 'btn btn-sm btn-outline-secondary';
                customBtn.textContent = 'Add custom';
                customBtn.addEventListener('click', () => addRegressorToModelX(basePath, customInput.value));
                controls.appendChild(customBtn);

                const currentModelX = normalizeStringArray(getByPath(modelEditorDraft, basePath));
                const usedSet = new Set(currentModelX);

                function removeRegressorFromModelX(reg) {
                    const arr = getByPath(modelEditorDraft, basePath);
                    if (!Array.isArray(arr)) return;
                    const next = arr.filter(v => String(v || '').trim() !== reg);
                    if (next.length === arr.length) return;
                    setByPath(modelEditorDraft, basePath, next);
                    renderModelAccordionEditor();
                }

                function toggleRegressorInModelX(reg) {
                    if (usedSet.has(reg)) {
                        removeRegressorFromModelX(reg);
                    } else {
                        addRegressorToModelX(basePath, reg);
                    }
                }

                const badgePoolRegs = uniqueRegs.filter(reg => !transformerRegressors.includes(reg));
                if (badgePoolRegs.length > 0) {
                    const regPool = document.createElement('div');
                    regPool.className = 'd-flex flex-wrap gap-2 w-100 mt-2';
                    badgePoolRegs.forEach(reg => {
                        const isUsed = usedSet.has(reg);
                        const badge = document.createElement('button');
                        badge.type = 'button';
                        badge.className = isUsed ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-outline-primary';
                        badge.textContent = reg;
                        badge.draggable = !isUsed;
                        badge.title = isUsed ? 'In Design Matrix — click to remove' : 'Click to add to Design Matrix';
                        badge.addEventListener('click', () => toggleRegressorInModelX(reg));
                        badge.addEventListener('dragstart', (event) => {
                            event.dataTransfer.effectAllowed = 'copy';
                            event.dataTransfer.setData('application/x-modelx-regressor', reg);
                            event.dataTransfer.setData('text/plain', reg);
                        });
                        regPool.appendChild(badge);
                    });
                    controls.appendChild(regPool);
                }

                // bidspm only ever executes Transformations for Run-level events.tsv data, so
                // suggesting transformer-generated regressors at other levels would be misleading.
                if (isRunModelX && (transformerRegressors.length || hasTransformerPipeline)) {
                    const transformerCard = document.createElement('div');
                    transformerCard.className = 'border rounded p-2 mb-2 bg-white w-100';

                    const transformerTitle = document.createElement('div');
                    transformerTitle.className = 'small fw-bold mb-1';
                    transformerTitle.textContent = 'Transformer-generated regressors';
                    transformerCard.appendChild(transformerTitle);

                    const transformerHint = document.createElement('div');
                    transformerHint.className = 'small text-muted mb-2';
                    transformerHint.textContent = transformerRegressors.length
                        ? 'Outputs from the attached transformer pipeline. Click or drag badges to add to the Design Matrix; click again to remove.'
                        : 'No generated transformer columns detected yet. Define Output names in Transformations to reuse them in Model.X.';
                    transformerCard.appendChild(transformerHint);

                    const transformerPool = document.createElement('div');
                    transformerPool.className = 'd-flex flex-wrap gap-2';

                    if (!transformerRegressors.length) {
                        const empty = document.createElement('div');
                        empty.className = 'small text-muted';
                        empty.textContent = 'Transformer outputs will appear here after you define generated columns.';
                        transformerPool.appendChild(empty);
                    } else {
                        transformerRegressors.forEach(reg => {
                            const isUsed = usedSet.has(reg);
                            const badge = document.createElement('button');
                            badge.type = 'button';
                            badge.className = isUsed ? 'btn btn-sm btn-success' : 'btn btn-sm btn-outline-success';
                            badge.textContent = reg;
                            badge.draggable = !isUsed;
                            badge.title = isUsed ? 'In Design Matrix — click to remove' : 'Click to add to Design Matrix';
                            badge.addEventListener('click', () => toggleRegressorInModelX(reg));
                            badge.addEventListener('dragstart', (event) => {
                                event.dataTransfer.effectAllowed = 'copy';
                                event.dataTransfer.setData('application/x-modelx-regressor', reg);
                                event.dataTransfer.setData('text/plain', reg);
                            });
                            transformerPool.appendChild(badge);
                        });
                    }

                    transformerCard.appendChild(transformerPool);
                    controls.appendChild(transformerCard);
                }

                if (!isDatasetModelX && isFirstLevelModelX) {
                    const nuisanceCard = document.createElement('div');
                    nuisanceCard.className = 'border rounded p-2 mb-2 bg-white w-100';

                    const NUISANCE_COLLAPSED_KEY = 'bidspm_nuisance_card_collapsed';
                    const isCollapsed = localStorage.getItem(NUISANCE_COLLAPSED_KEY) === '1';

                    const nuisanceHeader = document.createElement('div');
                    nuisanceHeader.className = 'd-flex justify-content-between align-items-center';
                    nuisanceHeader.style.cursor = 'pointer';
                    nuisanceHeader.setAttribute('role', 'button');
                    nuisanceHeader.setAttribute('title', 'Click to collapse / expand');

                    const nuisanceTitle = document.createElement('div');
                    nuisanceTitle.className = 'small fw-bold';
                    nuisanceTitle.textContent = 'Regressors of No Interest (fMRIPrep confounds)';

                    const nuisanceChevron = document.createElement('span');
                    nuisanceChevron.className = 'ms-2 text-muted';
                    nuisanceChevron.style.fontSize = '0.75rem';
                    nuisanceChevron.textContent = isCollapsed ? '▶' : '▼';

                    nuisanceHeader.appendChild(nuisanceTitle);
                    nuisanceHeader.appendChild(nuisanceChevron);
                    nuisanceCard.appendChild(nuisanceHeader);

                    const nuisanceBody = document.createElement('div');
                    nuisanceBody.style.display = isCollapsed ? 'none' : '';

                    const nuisanceHint = document.createElement('div');
                    nuisanceHint.className = 'small text-muted mb-2 mt-1';
                    nuisanceHint.textContent = modelEditorConfoundColumns.length
                        ? `Detected ${modelEditorConfoundColumns.length} confound columns. Use presets, search or per-group "+ all" to add to Design Matrix.`
                        : 'No confounds file detected yet. Set the fMRIPrep folder above and reload the model.';
                    nuisanceBody.appendChild(nuisanceHint);

                    const defaultTransRot = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z'];
                    const nuisancePicker = buildNuisanceRegressorPicker({
                        confoundColumns: modelEditorConfoundColumns,
                        curatedColumns: modelEditorTransRotConfounds.length ? modelEditorTransRotConfounds : defaultTransRot,
                        getSelectedSet: () => new Set(normalizeStringArray(getByPath(modelEditorDraft, basePath))),
                        onAdd: (reg) => addRegressorToModelX(basePath, reg),
                        onRemove: (reg) => {
                            const arr = getByPath(modelEditorDraft, basePath);
                            if (!Array.isArray(arr)) return;
                            const next = arr.filter(v => String(v || '').trim() !== reg);
                            if (next.length === arr.length) return;
                            setByPath(modelEditorDraft, basePath, next);
                            setModelEditorStatus(`Removed ${reg} from Model.X`, 'info');
                            renderModelAccordionEditor();
                        }
                    });
                    nuisanceBody.appendChild(nuisancePicker);
                    nuisanceCard.appendChild(nuisanceBody);

                    nuisanceHeader.addEventListener('click', () => {
                        const nowHidden = nuisanceBody.style.display !== 'none';
                        nuisanceBody.style.display = nowHidden ? 'none' : '';
                        nuisanceChevron.textContent = nowHidden ? '▶' : '▼';
                        localStorage.setItem(NUISANCE_COLLAPSED_KEY, nowHidden ? '1' : '0');
                    });

                    controls.appendChild(nuisanceCard);
                }

                const dmLabel = document.createElement('div');
                dmLabel.className = 'small fw-bold w-100 mt-1';
                dmLabel.textContent = 'Design Matrix space';
                controls.appendChild(dmLabel);

                const dropZone = document.createElement('div');
                dropZone.className = 'small text-muted border rounded p-2 w-100';
                dropZone.textContent = 'Drop regressor badges here or onto existing regressors to insert and reorder.';
                dropZone.addEventListener('dragover', (event) => {
                    const droppedRegressor = (event.dataTransfer.getData('application/x-modelx-regressor') || event.dataTransfer.getData('text/plain') || '').trim();
                    if (!droppedRegressor) return;
                    event.preventDefault();
                    dropZone.classList.add('bg-light');
                });
                dropZone.addEventListener('dragleave', () => {
                    dropZone.classList.remove('bg-light');
                });
                dropZone.addEventListener('drop', (event) => {
                    event.preventDefault();
                    dropZone.classList.remove('bg-light');
                    const droppedRegressor = (event.dataTransfer.getData('application/x-modelx-regressor') || event.dataTransfer.getData('text/plain') || '').trim();
                    if (!droppedRegressor) return;
                    addRegressorToModelX(basePath, droppedRegressor);
                });
                controls.appendChild(dropZone);

                listWrap.appendChild(controls);

                if (isRunModelX && !showModelAdvancedFields) {
                    const existingModulations = getParametricModulationsForCurrentX();
                    if (existingModulations.length) {
                        listWrap.appendChild(createAdvancedFieldsBadge(
                            `Parametric modulations (${existingModulations.length}) hidden`
                        ));
                    }
                } else if (isRunModelX) {
                    const modulationCard = document.createElement('div');
                    modulationCard.className = 'border rounded p-2 mb-2 bg-white d-flex flex-column gap-2';

                    const modulationHeader = document.createElement('div');
                    modulationHeader.className = 'd-flex justify-content-between align-items-center';
                    const modulationTitle = document.createElement('div');
                    modulationTitle.className = 'small fw-bold';
                    modulationTitle.textContent = 'Parametric Modulation (optional)';
                    const modulationToggle = document.createElement('input');
                    modulationToggle.type = 'checkbox';
                    modulationToggle.className = 'form-check-input';
                    const existingModulations = getParametricModulationsForCurrentX();
                    modulationToggle.checked = existingModulations.length > 0;
                    modulationHeader.appendChild(modulationTitle);
                    modulationHeader.appendChild(modulationToggle);
                    modulationCard.appendChild(modulationHeader);

                    const modulationHint = document.createElement('div');
                    modulationHint.className = 'small text-muted';
                    modulationHint.textContent = 'Select a condition regressor and numeric events.tsv column (for example rating). Saved to Model.Software.SPM.ParametricModulations.';
                    modulationCard.appendChild(modulationHint);

                    const availableConditions = getConditionRegressorsForModulation();
                    const availableValues = getNumericColumnsForModulation();

                    if (!availableConditions.length) {
                        const warn = document.createElement('div');
                        warn.className = 'small text-warning';
                        warn.textContent = 'Add a condition regressor (e.g. trial_type.*, condition.*, or a Transformations-derived column.level name) to Model.X before enabling modulation.';
                        modulationCard.appendChild(warn);
                    }
                    if (!availableValues.length) {
                        const warn = document.createElement('div');
                        warn.className = 'small text-warning';
                        warn.textContent = 'No numeric events.tsv columns detected for selected tasks.';
                        modulationCard.appendChild(warn);
                    }

                    modulationToggle.addEventListener('change', () => {
                        if (!modulationToggle.checked) {
                            setParametricModulationsForCurrentX([]);
                            setModelEditorStatus('Parametric modulation disabled.', 'info');
                            renderModelAccordionEditor();
                            return;
                        }
                        setParametricModulationsForCurrentX([
                            normalizeParametricModulationEntry({}, availableConditions[0] || '', availableValues[0] || '', 0)
                        ]);
                        setModelEditorStatus('Parametric modulation enabled.', 'info');
                        renderModelAccordionEditor();
                    });

                    if (existingModulations.length) {
                        existingModulations.forEach((entry, modIdx) => {
                            const row = document.createElement('div');
                            row.className = 'border rounded p-2 bg-light-subtle d-flex flex-column gap-2';

                            const rowTop = document.createElement('div');
                            rowTop.className = 'd-flex justify-content-between align-items-center';
                            const rowLabel = document.createElement('div');
                            rowLabel.className = 'small fw-bold';
                            rowLabel.textContent = `Modulation ${modIdx + 1}`;
                            const removeBtn = document.createElement('button');
                            removeBtn.type = 'button';
                            removeBtn.className = 'btn btn-sm btn-outline-danger';
                            removeBtn.textContent = 'Remove';
                            removeBtn.addEventListener('click', () => {
                                const next = getParametricModulationsForCurrentX();
                                next.splice(modIdx, 1);
                                setParametricModulationsForCurrentX(next);
                                setModelEditorStatus('Parametric modulation removed.', 'info');
                                renderModelAccordionEditor();
                            });
                            rowTop.appendChild(rowLabel);
                            rowTop.appendChild(removeBtn);
                            row.appendChild(rowTop);

                            const nameInput = document.createElement('input');
                            nameInput.type = 'text';
                            nameInput.className = 'form-control form-control-sm';
                            nameInput.placeholder = 'Name (for example idea_rating_mod)';
                            nameInput.value = entry.Name;
                            nameInput.addEventListener('change', () => {
                                const next = getParametricModulationsForCurrentX();
                                next[modIdx].Name = (nameInput.value || '').trim() || `parametric_mod_${modIdx + 1}`;
                                setParametricModulationsForCurrentX(next);
                                setModelEditorStatus('Parametric modulation updated.', 'info');
                                renderModelAccordionEditor();
                            });
                            row.appendChild(nameInput);

                            const conditionSelect = document.createElement('select');
                            conditionSelect.className = 'form-select form-select-sm';
                            const currentCondition = normalizeStringArray(entry.Conditions)[0] || '';
                            const conditionChoices = Array.from(new Set([...availableConditions, currentCondition].filter(Boolean)));
                            const emptyCondition = document.createElement('option');
                            emptyCondition.value = '';
                            emptyCondition.textContent = conditionChoices.length ? 'Select condition regressor' : 'No condition regressors available';
                            conditionSelect.appendChild(emptyCondition);
                            conditionChoices.forEach(choice => {
                                const opt = document.createElement('option');
                                opt.value = choice;
                                opt.textContent = choice;
                                conditionSelect.appendChild(opt);
                            });
                            conditionSelect.value = currentCondition;
                            conditionSelect.addEventListener('change', () => {
                                const next = getParametricModulationsForCurrentX();
                                next[modIdx].Conditions = conditionSelect.value ? [conditionSelect.value] : [];
                                setParametricModulationsForCurrentX(next);
                                setModelEditorStatus('Parametric modulation updated.', 'info');
                                renderModelAccordionEditor();
                            });
                            row.appendChild(conditionSelect);

                            const valueSelect = document.createElement('select');
                            valueSelect.className = 'form-select form-select-sm';
                            const currentValue = normalizeStringArray(entry.Values)[0] || '';
                            const valueChoices = Array.from(new Set([...availableValues, currentValue].filter(Boolean)));
                            const emptyValue = document.createElement('option');
                            emptyValue.value = '';
                            emptyValue.textContent = valueChoices.length ? 'Select numeric events.tsv column' : 'No numeric columns available';
                            valueSelect.appendChild(emptyValue);
                            valueChoices.forEach(choice => {
                                const opt = document.createElement('option');
                                opt.value = choice;
                                opt.textContent = choice;
                                valueSelect.appendChild(opt);
                            });
                            valueSelect.value = currentValue;
                            valueSelect.addEventListener('change', () => {
                                const next = getParametricModulationsForCurrentX();
                                next[modIdx].Values = valueSelect.value ? [valueSelect.value] : [];
                                setParametricModulationsForCurrentX(next);
                                setModelEditorStatus('Parametric modulation updated.', 'info');
                                renderModelAccordionEditor();
                            });
                            row.appendChild(valueSelect);

                            const valueSamples = getNumericSamplesForColumn(currentValue);
                            if (valueSamples.length) {
                                const sampleHint = document.createElement('div');
                                sampleHint.className = 'small text-muted';
                                sampleHint.textContent = `Sample ${currentValue}: ${valueSamples.slice(0, 5).join(', ')}`;
                                row.appendChild(sampleHint);
                            }

                            const polyInput = document.createElement('input');
                            polyInput.type = 'number';
                            polyInput.className = 'form-control form-control-sm';
                            polyInput.min = '1';
                            polyInput.step = '1';
                            polyInput.value = String(entry.PolynomialExpansion || 1);
                            polyInput.placeholder = 'Polynomial expansion (1 = linear)';
                            polyInput.addEventListener('change', () => {
                                const next = getParametricModulationsForCurrentX();
                                const parsed = Number(polyInput.value);
                                next[modIdx].PolynomialExpansion = Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : 1;
                                setParametricModulationsForCurrentX(next);
                                setModelEditorStatus('Parametric modulation updated.', 'info');
                                renderModelAccordionEditor();
                            });
                            row.appendChild(polyInput);

                            modulationCard.appendChild(row);
                        });

                        const addModulationBtn = document.createElement('button');
                        addModulationBtn.type = 'button';
                        addModulationBtn.className = 'btn btn-sm btn-outline-primary align-self-start';
                        addModulationBtn.textContent = 'Add Modulation';
                        addModulationBtn.addEventListener('click', () => {
                            const next = getParametricModulationsForCurrentX();
                            next.push(normalizeParametricModulationEntry({}, availableConditions[0] || '', availableValues[0] || '', next.length));
                            setParametricModulationsForCurrentX(next);
                            setModelEditorStatus('Parametric modulation added.', 'info');
                            renderModelAccordionEditor();
                        });
                        modulationCard.appendChild(addModulationBtn);
                    }

                    listWrap.appendChild(modulationCard);
                }
            }

            if (/\.GroupBy$/.test(basePath)) {
                const controls = document.createElement('div');
                controls.className = 'd-flex flex-wrap gap-2 align-items-center p-2 mb-2 border rounded bg-white groupby-controls';

                const current = Array.isArray(node) ? node : [];
                const remaining = (modelEditorGroupByOptions || ['subject']).filter(opt => !current.includes(opt));

                const select = document.createElement('select');
                select.className = 'form-select form-select-sm';
                select.style.maxWidth = '260px';
                const sourceOptions = remaining.length ? remaining : (modelEditorGroupByOptions || ['subject']);
                sourceOptions.forEach(optVal => {
                    const opt = document.createElement('option');
                    opt.value = optVal;
                    opt.textContent = optVal;
                    select.appendChild(opt);
                });
                controls.appendChild(select);

                const addBtn = document.createElement('button');
                addBtn.type = 'button';
                addBtn.className = 'btn btn-sm btn-outline-success';
                addBtn.textContent = '+ Add';
                addBtn.disabled = remaining.length === 0;
                addBtn.addEventListener('click', () => {
                    const value = select.value;
                    const arr = getByPath(modelEditorDraft, basePath);
                    if (!Array.isArray(arr)) return;
                    if (arr.includes(value)) {
                        const status = document.getElementById('model-editor-status');
                        status.innerHTML = `<div class="alert alert-warning py-1 x-small mb-2">GroupBy already selected: ${value}</div>`;
                        return;
                    }
                    arr.push(value);
                    renderModelAccordionEditor();
                });
                controls.appendChild(addBtn);

                listWrap.appendChild(controls);
            }

            node.forEach((item, idx) => {
                const itemPath = `${basePath}[${idx}]`;
                const locked = inheritedLocked || isReadonlyModelPath(itemPath);
                // User-friendly label: show value for primitives, name/index for objects
                let displayLabel;
                if (item !== null && typeof item === 'object') {
                    displayLabel = item.Name || `#${idx + 1}`;
                } else {
                    displayLabel = item !== null && item !== '' ? String(item) : `#${idx + 1}`;
                }
                if (item !== null && typeof item === 'object') {
                    createBranchAccordion(listWrap, displayLabel, itemPath, item, locked, depth);
                } else {
                    createPrimitiveRow(listWrap, `#${idx + 1}`, item, itemPath, locked, depth);
                }
            });
            container.appendChild(listWrap);
            return;
        }

        if (node !== null && typeof node === 'object') {
            const isManagedHrfObject = isManagedModelHrfPath(basePath);
            if (isManagedHrfObject) {
                container.appendChild(createInlineNote('HRF variables are controlled in Design Matrix rows. Use each regressor\'s HRF on/off toggle.'));
            }

            if (/^Nodes\[\d+\]\.Model\.HRF$/.test(basePath)) {
                const modelObj = getByPath(modelEditorDraft, basePath.replace(/\.HRF$/, ''));
                const modelX = Array.isArray(modelObj?.X)
                    ? modelObj.X.map(item => String(item || '').trim()).filter(Boolean)
                    : [];
                container.appendChild(createHrfSchemaHint(node, modelX));
            }

            if (/^Nodes\[\d+\]\.Model\.Options$/.test(basePath)) {
                container.appendChild(createOptionsSchemaHint(node));
            }

            if (/^Nodes\[\d+\]\.Contrasts\[\d+\]$/.test(basePath)) {
                container.appendChild(createContrastSchemaHint(node));
            }

            if (/^Nodes\[\d+\]\.DummyContrasts$/.test(basePath)) {
                const modelObj = getByPath(modelEditorDraft, basePath.replace(/\.DummyContrasts$/, '.Model'));
                const modelX = Array.isArray(modelObj?.X)
                    ? modelObj.X.map(item => String(item || '').trim()).filter(Boolean)
                    : [];
                container.appendChild(createDummyContrastsSchemaHint(node, modelX));
            }

            if (/^Nodes\[\d+\]\.Transformations$/.test(basePath)) {
                container.appendChild(createTransformationsSchemaHint(node));
            }

            if (/^Edges\[\d+\]$/.test(basePath)) {
                const nodeNames = Array.isArray(modelEditorDraft?.Nodes)
                    ? modelEditorDraft.Nodes.map(item => String(item?.Name || '').trim()).filter(Boolean)
                    : [];
                const knownFilterKeys = getKnownEdgeFilterMetadataKeys();
                container.appendChild(createEdgeSchemaHint(node, nodeNames, knownFilterKeys));
                container.appendChild(createEdgeWorkspaceFields(node));
            }

            if (/^Nodes\[\d+\]\.Model$/.test(basePath)) {
                container.appendChild(createModelSchemaHint(node));
            }

            if (/^Nodes\[\d+\]$/.test(basePath)) {
                container.appendChild(createNodeSchemaHint(node));
            }

            const datasetPresetPanel = createDatasetModelPresetPanel(basePath);
            if (datasetPresetPanel) {
                container.appendChild(datasetPresetPanel);
            }

            // Mask quick-set panel for Node objects
            if (/^Nodes\[\d+\]$/.test(basePath)) {
                container.appendChild(createNodeIdentityEditor(node));
                container.appendChild(createNodeMaskPicker(node));
                container.appendChild(createAddTransformationsPanel(node, basePath));
                container.appendChild(createDummyContrastsPanel(node, basePath));
                const nodeMatch = String(basePath).match(/^Nodes\[(\d+)\]$/);
                const nodeIdx = nodeMatch ? Number(nodeMatch[1]) : -1;
                container.appendChild(createContrastManagerPanel(node, nodeIdx));
            }

            const objWrap = document.createElement('div');
            objWrap.className = 'accordion';
            Object.entries(node).forEach(([key, value]) => {
                if (/^Nodes\[\d+\]$/.test(basePath) && (key === 'Level' || key === 'Name')) {
                    return;
                }
                if (/^Nodes\[\d+\]$/.test(basePath) && ['Transformations', 'DummyContrasts', 'Contrasts'].includes(key)) {
                    return;
                }
                if (/^Edges\[\d+\]$/.test(basePath) && ['Source', 'Destination', 'Filter'].includes(key)) {
                    return;
                }
                if (isManagedHrfObject && key === 'Variables') {
                    return;
                }
                if (key === 'Description' && !showModelAdvancedFields) {
                    if (value) {
                        objWrap.appendChild(createAdvancedFieldsBadge('Description hidden'));
                    }
                    return;
                }
                const path = basePath ? `${basePath}.${key}` : key;
                const locked = inheritedLocked || isReadonlyModelPath(path);
                if (value !== null && typeof value === 'object') {
                    createBranchAccordion(objWrap, key, path, value, locked, depth);
                } else {
                    createPrimitiveRow(objWrap, key, value, path, locked, depth);
                }
            });
            container.appendChild(objWrap);
            return;
        }

        createPrimitiveRow(container, basePath || 'value', node, basePath || 'value', inheritedLocked, depth);
    }

    function reorderModelOverviewKeys(model) {
        // Description is only ever added to a model via setByPath, which -- like any
        // plain JS object assignment -- inserts brand-new keys at the end. For a
        // model with a large Nodes array that puts "Description" far past what's
        // visible in the JSON preview without scrolling, even though it's right next
        // to "Name" in the editor UI above. Reorder so the two stay in sync.
        if (!model || typeof model !== 'object' || Array.isArray(model) || !('Description' in model)) {
            return;
        }
        const leadingKeys = ['Name', 'BIDSModelVersion', 'Description'].filter(key => key in model);
        const snapshot = { ...model };
        Object.keys(model).forEach(key => { delete model[key]; });
        leadingKeys.forEach(key => { model[key] = snapshot[key]; });
        Object.keys(snapshot).forEach(key => {
            if (!leadingKeys.includes(key)) model[key] = snapshot[key];
        });
    }

    function renderModelAccordionEditor() {
        const editor = document.getElementById('model-editor-accordion');
        const status = document.getElementById('model-editor-status');

        // Save which collapse panels are currently open so we can restore them after re-render
        const openPaths = new Set(
            Array.from(editor.querySelectorAll('.accordion-collapse.show'))
                 .map(el => el.dataset.jsonPath || '')
                 .filter(Boolean)
        );
        if (modelEditorPendingOpenPaths.size) {
            modelEditorPendingOpenPaths.forEach(path => openPaths.add(path));
            modelEditorPendingOpenPaths.clear();
        }
        modelEditorOpenPaths = openPaths;

        editor.innerHTML = '';

        if (!modelEditorDraft || typeof modelEditorDraft !== 'object') {
            renderModelEditorSummary(null);
            updateModelJsonPreview();
            editor.innerHTML = '<div class="text-muted small">No model loaded.</div>';
            return;
        }

        reorderModelOverviewKeys(modelEditorDraft);

        const missing = REQUIRED_ROOT_KEYS.filter(k => !(k in modelEditorDraft));
        if (missing.length) {
            status.innerHTML = `<div class="alert alert-warning py-1 x-small mb-2">Missing required keys: ${missing.join(', ')}</div>`;
        }

        if (!Array.isArray(modelEditorDraft.Input?.task)) {
            if (!modelEditorDraft.Input || typeof modelEditorDraft.Input !== 'object') {
                modelEditorDraft.Input = {};
            }
            modelEditorDraft.Input.task = [];
        }

        syncAllModelXHrfVariables();

        const summary = computeModelEditorSummary(modelEditorDraft);
        renderModelEditorSummary(summary);
        summary.sections.forEach(section => createModelSectionCard(editor, section));
        updateModelJsonPreview();
    }
