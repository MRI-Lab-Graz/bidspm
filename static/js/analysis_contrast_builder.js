(function () {
    function createContrastBuilder(config = {}) {
        const bootstrapImpl = config.bootstrapImpl || window.bootstrap;
        const getElement = config.getElement || ((id) => document.getElementById(id));
        const querySelectorAll = config.querySelectorAll || ((selector) => document.querySelectorAll(selector));
        const alertImpl = config.alertImpl || window.alert.bind(window);
        const nuisanceRegressorRx = config.nuisanceRegressorRx || /$^/;

        let cbNodeIdx = 0;
        let cbDraft = null;
        let cbConditions = [];

        let dragChip = null;
        let dragFromCardIdx = null;
        let dragFromCondIdx = null;
        let dragCardIdx = null;

        const modal = getElement('contrastBuilderModal');
        const nodeTabs = getElement('cb-node-tabs');
        const noNodesMsg = getElement('cb-no-nodes-msg');
        const condPool = getElement('cb-condition-pool');
        const contrastList = getElement('cb-contrast-list');
        const cbStatus = getElement('cb-status');
        const applyBtn = getElement('cb-apply-btn');
        const addContrastBtn = getElement('cb-add-contrast-btn');
        const addCustomBtn = getElement('cb-add-custom-btn');
        const customCondInput = getElement('cb-custom-condition');

        function getNodes() {
            const draft = config.getModelDraft?.();
            return draft && Array.isArray(draft.Nodes) ? draft.Nodes : [];
        }

        function currentNode() {
            return getNodes()[cbNodeIdx] || null;
        }

        // 'condition:pmodName^order' addresses a parametric modulation term rather than a
        // condition's main effect -- see getRegressorIdx.m for the matching SPM-side syntax.
        function pmodTermId(condition, pmodName, order) {
            return `${condition}:${pmodName}^${order}`;
        }

        function buildParametricModulationTerms(node) {
            const terms = [];
            const modulations = node?.Model?.Software?.SPM?.ParametricModulations;
            if (!Array.isArray(modulations)) return terms;
            modulations.forEach((entry) => {
                const name = String(entry?.Name || '').trim();
                if (!name) return;
                const conditions = Array.isArray(entry?.Conditions) ? entry.Conditions : [];
                const maxOrder = Number(entry?.PolynomialExpansion) > 0 ? Math.round(Number(entry.PolynomialExpansion)) : 1;
                conditions.forEach((condition) => {
                    if (typeof condition !== 'string' || !condition.trim()) return;
                    for (let order = 1; order <= maxOrder; order += 1) {
                        terms.push(pmodTermId(condition.trim(), name, order));
                    }
                });
            });
            return terms;
        }

        function buildConditions() {
            const pool = new Set(config.getSuggestedConditionTermsForNode?.(cbNodeIdx) || config.getInterestRegressors?.() || []);
            const node = currentNode();
            const incomingContrastNames = config.getIncomingContrastNamesForNode?.(cbNodeIdx) || [];
            incomingContrastNames.forEach((name) => pool.add(name));
            if (node) {
                (node.Model?.X || []).forEach((value) => {
                    if (typeof value === 'string' && !nuisanceRegressorRx.test(value.trim())) {
                        pool.add(value.trim());
                    }
                });
                (node.Contrasts || []).forEach((contrast) => {
                    (contrast.ConditionList || []).forEach((condition) => pool.add(condition));
                });
                buildParametricModulationTerms(node).forEach((term) => pool.add(term));
            }
            const conditions = Array.from(pool).filter(Boolean);
            if (!conditions.includes('1')) conditions.push('1');
            return conditions.sort((left, right) => left.localeCompare(right));
        }

        function cloneContrasts() {
            const node = currentNode();
            if (!node) return [];
            return structuredClone(Array.isArray(node.Contrasts) ? node.Contrasts : []);
        }

        function defaultContrastName() {
            return `Contrast_${String(Date.now()).slice(-4)}`;
        }

        function sumWeights(contrast) {
            return (contrast.Weights || []).reduce((sum, weight) => sum + Number(weight), 0);
        }

        function conditionLabel(condition) {
            if (condition === '1') return 'constant (intercept)';
            const pmodMatch = /^(.+):(.+)\^(\d+)$/.exec(condition);
            if (pmodMatch) {
                const [, baseCondition, pmodName, order] = pmodMatch;
                const orderLabel = order === '1' ? 'linear' : order === '2' ? 'quadratic' : `order ${order}`;
                return `${baseCondition} × ${pmodName} (${orderLabel} pmod)`;
            }
            return condition;
        }

        function renderNodeTabs() {
            if (!nodeTabs || !noNodesMsg) return;
            nodeTabs.innerHTML = '';
            const nodes = getNodes();
            if (!nodes.length) {
                noNodesMsg.classList.remove('d-none');
                return;
            }
            noNodesMsg.classList.add('d-none');
            nodes.forEach((node, index) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = `cb-node-tab ${index === cbNodeIdx ? 'active' : ''}`;
                button.textContent = `${node.Level || 'Node'} – ${node.Name || `#${index + 1}`}`;
                button.addEventListener('click', () => {
                    cbNodeIdx = index;
                    reloadForNode();
                });
                nodeTabs.appendChild(button);
            });
        }

        function renderConditionPool() {
            if (!condPool) return;
            condPool.innerHTML = '';
            if (!cbConditions.length) {
                condPool.innerHTML = '<div class="text-muted small">No conditions detected. Set BIDS folder first.</div>';
                return;
            }
            cbConditions.forEach((condition) => {
                condPool.appendChild(makeChip(condition));
            });
        }

        function makeChip(condition) {
            const chip = document.createElement('div');
            chip.className = 'cb-condition-chip';
            chip.draggable = true;
            chip.dataset.cond = condition;
            chip.innerHTML = `<i class="fas fa-grip-vertical cb-chip-icon"></i><span>${conditionLabel(condition)}</span>`;
            chip.addEventListener('dragstart', (event) => {
                dragChip = condition;
                dragFromCardIdx = null;
                dragFromCondIdx = null;
                dragCardIdx = null;
                chip.classList.add('dragging');
                event.dataTransfer.effectAllowed = 'copy';
                event.dataTransfer.setData('text/plain', condition);
            });
            chip.addEventListener('dragend', () => chip.classList.remove('dragging'));
            return chip;
        }

        function renderContrastList() {
            if (!contrastList) return;
            contrastList.innerHTML = '';
            if (!cbDraft.length) {
                const empty = document.createElement('div');
                empty.className = 'cb-empty-state';
                empty.innerHTML = `<i class="fas fa-arrow-left fa-2x mb-2 d-block opacity-25"></i>
                    Drag conditions from the left panel<br>and click <strong>Add Contrast</strong> to start.`;
                contrastList.appendChild(empty);
                return;
            }
            cbDraft.forEach((contrast, index) => renderContrastCard(index));
        }

        function renderContrastCard(index) {
            const contrast = cbDraft[index];
            const card = document.createElement('div');
            card.className = 'cb-contrast-card';
            card.dataset.idx = index;
            card.draggable = false;

            const header = document.createElement('div');
            header.className = 'cb-contrast-header';

            const grab = document.createElement('span');
            grab.className = 'cb-contrast-grab';
            grab.title = 'Drag to reorder contrasts';
            grab.innerHTML = '<i class="fas fa-grip-vertical"></i>';
            grab.draggable = true;
            grab.addEventListener('dragstart', (event) => {
                dragCardIdx = index;
                dragChip = null;
                card.classList.add('cb-dragging-card');
                event.dataTransfer.effectAllowed = 'move';
            });
            grab.addEventListener('dragend', () => card.classList.remove('cb-dragging-card'));
            header.appendChild(grab);

            const nameInput = document.createElement('input');
            nameInput.type = 'text';
            nameInput.className = 'cb-contrast-name-input';
            nameInput.value = contrast.Name || '';
            nameInput.placeholder = 'Contrast name';
            nameInput.addEventListener('input', () => {
                cbDraft[index].Name = nameInput.value;
            });
            header.appendChild(nameInput);

            const testSelect = document.createElement('select');
            testSelect.className = 'cb-test-type-select';
            ['t', 'F'].forEach((testType) => {
                const option = document.createElement('option');
                option.value = testType;
                option.textContent = `${testType}-test`;
                if (contrast.Test === testType) option.selected = true;
                testSelect.appendChild(option);
            });
            testSelect.addEventListener('change', () => {
                cbDraft[index].Test = testSelect.value;
            });
            header.appendChild(testSelect);

            const weightSum = document.createElement('span');
            const sum = sumWeights(contrast);
            weightSum.className = `cb-weight-sum ${Math.abs(sum) < 0.001 ? 'cb-weight-sum-ok' : 'cb-weight-sum-warn'}`;
            weightSum.title = 'Sum of weights (should be 0 for t-tests across conditions)';
            weightSum.textContent = `Σ = ${sum % 1 === 0 ? sum : sum.toFixed(3)}`;
            header.appendChild(weightSum);

            const actions = document.createElement('div');
            actions.className = 'cb-contrast-actions';

            const vsRestBtn = document.createElement('button');
            vsRestBtn.type = 'button';
            vsRestBtn.className = 'btn btn-sm btn-outline-secondary';
            vsRestBtn.title = 'Auto: each +1, others split equally negative';
            vsRestBtn.innerHTML = '<i class="fas fa-balance-scale"></i>';
            vsRestBtn.addEventListener('click', () => {
                applyVsRestPreset(index);
                renderContrastList();
            });
            actions.appendChild(vsRestBtn);

            const flipBtn = document.createElement('button');
            flipBtn.type = 'button';
            flipBtn.className = 'btn btn-sm btn-outline-secondary';
            flipBtn.title = 'Flip all weights';
            flipBtn.innerHTML = '<i class="fas fa-exchange-alt"></i>';
            flipBtn.addEventListener('click', () => {
                cbDraft[index].Weights = (cbDraft[index].Weights || []).map((weight) => -Number(weight));
                renderContrastList();
            });
            actions.appendChild(flipBtn);

            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'btn btn-sm btn-outline-danger';
            deleteBtn.title = 'Delete contrast';
            deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
            deleteBtn.addEventListener('click', () => {
                cbDraft.splice(index, 1);
                renderContrastList();
            });
            actions.appendChild(deleteBtn);
            header.appendChild(actions);
            card.appendChild(header);

            const body = document.createElement('div');
            body.className = 'cb-contrast-body';

            const dropZone = document.createElement('div');
            dropZone.className = 'cb-drop-zone';
            if (!(contrast.ConditionList || []).length) {
                const hint = document.createElement('div');
                hint.className = 'cb-drop-zone-hint';
                hint.textContent = '← drag a condition here';
                dropZone.appendChild(hint);
            }

            dropZone.addEventListener('dragover', (event) => {
                if (dragChip !== null || (dragFromCardIdx === index && dragFromCondIdx !== null)) {
                    event.preventDefault();
                    dropZone.classList.add('drag-over');
                }
            });
            dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
            dropZone.addEventListener('drop', (event) => {
                event.preventDefault();
                dropZone.classList.remove('drag-over');
                if (dragChip !== null) {
                    addConditionToContrast(index, dragChip);
                    dragChip = null;
                    renderContrastList();
                }
            });

            (contrast.ConditionList || []).forEach((condition, conditionIndex) => {
                const weight = (contrast.Weights || [])[conditionIndex] ?? 0;
                dropZone.appendChild(buildConditionRow(index, conditionIndex, condition, weight));
            });

            body.appendChild(dropZone);
            if ((contrast.ConditionList || []).length) {
                body.appendChild(buildEquationLine(contrast));
            }
            card.appendChild(body);

            card.addEventListener('dragover', (event) => {
                if (dragCardIdx !== null && dragCardIdx !== index) {
                    event.preventDefault();
                    card.classList.add('drag-over');
                }
            });
            card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
            card.addEventListener('drop', (event) => {
                if (dragCardIdx !== null && dragCardIdx !== index) {
                    event.preventDefault();
                    card.classList.remove('drag-over');
                    const moved = cbDraft.splice(dragCardIdx, 1)[0];
                    cbDraft.splice(index, 0, moved);
                    dragCardIdx = null;
                    renderContrastList();
                }
            });

            contrastList.appendChild(card);
        }

        function buildConditionRow(cardIdx, condIdx, condition, weight) {
            const row = document.createElement('div');
            row.className = 'cb-condition-row';
            row.draggable = true;
            row.dataset.condIdx = condIdx;

            row.addEventListener('dragstart', (event) => {
                dragFromCardIdx = cardIdx;
                dragFromCondIdx = condIdx;
                dragChip = null;
                dragCardIdx = null;
                event.dataTransfer.effectAllowed = 'move';
            });
            row.addEventListener('dragover', (event) => {
                if (dragFromCardIdx === cardIdx && dragFromCondIdx !== condIdx) {
                    event.preventDefault();
                    row.classList.add('drag-over-row');
                }
            });
            row.addEventListener('dragleave', () => row.classList.remove('drag-over-row'));
            row.addEventListener('drop', (event) => {
                event.preventDefault();
                row.classList.remove('drag-over-row');
                if (dragFromCardIdx === cardIdx && dragFromCondIdx !== condIdx) {
                    const conditions = cbDraft[cardIdx].ConditionList;
                    const weights = cbDraft[cardIdx].Weights;
                    [conditions[dragFromCondIdx], conditions[condIdx]] = [conditions[condIdx], conditions[dragFromCondIdx]];
                    [weights[dragFromCondIdx], weights[condIdx]] = [weights[condIdx], weights[dragFromCondIdx]];
                    dragFromCondIdx = null;
                    dragFromCardIdx = null;
                    renderContrastList();
                }
            });

            const grip = document.createElement('i');
            grip.className = 'fas fa-grip-vertical text-muted small';
            grip.style.cursor = 'grab';
            row.appendChild(grip);

            const label = document.createElement('span');
            label.className = 'cb-cond-label';
            label.title = condition;
            label.textContent = conditionLabel(condition);
            row.appendChild(label);

            const controls = document.createElement('div');
            controls.className = 'cb-weight-ctrl';

            const quick = document.createElement('div');
            quick.className = 'cb-weight-quick';
            [['−1', -1], ['0', 0], ['+1', 1]].forEach(([labelText, value]) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'cb-wbtn';
                button.textContent = labelText;
                const numericWeight = Number(weight);
                if (value === 1 && numericWeight > 0 && Math.abs(numericWeight - 1) < 0.001) button.classList.add('active-pos');
                else if (value === -1 && numericWeight < 0 && Math.abs(numericWeight + 1) < 0.001) button.classList.add('active-neg');
                else if (value === 0 && Math.abs(numericWeight) < 0.001) button.classList.add('active-zero');
                button.addEventListener('click', () => {
                    cbDraft[cardIdx].Weights[condIdx] = value;
                    renderContrastList();
                });
                quick.appendChild(button);
            });
            controls.appendChild(quick);

            const weightInput = document.createElement('input');
            weightInput.type = 'number';
            weightInput.step = 'any';
            weightInput.className = 'cb-weight-input';
            weightInput.value = weight;
            weightInput.title = 'Custom weight';
            weightInput.addEventListener('change', () => {
                const numericValue = parseFloat(weightInput.value);
                cbDraft[cardIdx].Weights[condIdx] = Number.isNaN(numericValue) ? 0 : numericValue;
                renderContrastList();
            });
            controls.appendChild(weightInput);
            row.appendChild(controls);

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'cb-remove-cond';
            removeBtn.title = 'Remove from contrast';
            removeBtn.innerHTML = '<i class="fas fa-times"></i>';
            removeBtn.addEventListener('click', () => {
                cbDraft[cardIdx].ConditionList.splice(condIdx, 1);
                cbDraft[cardIdx].Weights.splice(condIdx, 1);
                renderContrastList();
            });
            row.appendChild(removeBtn);

            return row;
        }

        function buildEquationLine(contrast) {
            const parts = [];
            (contrast.ConditionList || []).forEach((condition, index) => {
                const weight = Number((contrast.Weights || [])[index] ?? 0);
                const sign = weight >= 0 ? '+' : '−';
                const absolute = Math.abs(weight);
                const weightPrefix = absolute === 1 ? '' : `${absolute}×`;
                if (index === 0) {
                    parts.push(`${weight < 0 ? '−' : ''}${weightPrefix}${condition}`);
                } else {
                    if (absolute < 0.001) return;
                    parts.push(` ${sign} ${weightPrefix}${condition}`);
                }
            });
            const line = document.createElement('div');
            line.className = 'x-small text-muted mt-2 font-monospace';
            line.style.overflowX = 'auto';
            line.style.whiteSpace = 'nowrap';
            line.textContent = parts.join('') || '(empty)';
            return line;
        }

        function addConditionToContrast(cardIdx, condition) {
            const contrast = cbDraft[cardIdx];
            if (!contrast.ConditionList) contrast.ConditionList = [];
            if (!contrast.Weights) contrast.Weights = [];
            if (contrast.ConditionList.includes(condition)) return;
            let defaultWeight = 0;
            const positiveCount = contrast.Weights.filter((weight) => weight > 0).length;
            const negativeCount = contrast.Weights.filter((weight) => weight < 0).length;
            if (positiveCount === 0) defaultWeight = 1;
            else if (negativeCount === 0) defaultWeight = -1;
            contrast.ConditionList.push(condition);
            contrast.Weights.push(defaultWeight);
        }

        function applyVsRestPreset(cardIdx) {
            const contrast = cbDraft[cardIdx];
            const count = (contrast.ConditionList || []).length;
            if (!count) return;
            const negativeWeight = count > 1 ? -(1 / (count - 1)) : -1;
            contrast.Weights = contrast.ConditionList.map((_, index) => (index === 0 ? 1 : negativeWeight));
        }

        function applyPreset(preset) {
            const conditions = cbConditions.filter((condition) => condition !== '1');
            if (!conditions.length) {
                showStatus('No conditions available for preset. Set BIDS folder first.', 'danger');
                return;
            }

            switch (preset) {
                case 'each-vs-rest':
                    cbDraft = [];
                    conditions.forEach((condition) => {
                        const others = conditions.filter((entry) => entry !== condition);
                        const negativeWeight = others.length > 0 ? -(1 / others.length) : -1;
                        const name = condition.replace(/^trial_type\.|^condition\./, '');
                        cbDraft.push({
                            Name: name,
                            ConditionList: [condition, ...others],
                            Weights: [1, ...others.map(() => negativeWeight)],
                            Test: 't'
                        });
                    });
                    break;
                case 'each-vs-baseline':
                    cbDraft = [];
                    conditions.forEach((condition) => {
                        const name = condition.replace(/^trial_type\.|^condition\./, '');
                        cbDraft.push({
                            Name: name,
                            ConditionList: [condition, '1'],
                            Weights: [1, -1],
                            Test: 't'
                        });
                    });
                    break;
                case 'all-active':
                    cbDraft = [{
                        Name: 'all_active',
                        ConditionList: conditions,
                        Weights: conditions.map(() => 1),
                        Test: 'F'
                    }];
                    break;
                case 'clear-all':
                    if (cbDraft.length && !window.confirm('Remove all contrasts for this node?')) return;
                    cbDraft = [];
                    break;
                default:
                    return;
            }

            renderContrastList();
        }

        function reloadForNode() {
            cbConditions = buildConditions();
            cbDraft = cloneContrasts();
            renderNodeTabs();
            renderConditionPool();
            renderContrastList();
            if (cbStatus) cbStatus.innerHTML = '';
        }

        function showStatus(message, type = 'info') {
            if (!cbStatus) return;
            const classMap = {
                info: 'text-primary',
                success: 'text-success',
                danger: 'text-danger',
                warn: 'text-warning'
            };
            cbStatus.innerHTML = `<span class="${classMap[type] || 'text-muted'}">${message}</span>`;
            if (type === 'success') {
                setTimeout(() => {
                    if (cbStatus) cbStatus.innerHTML = '';
                }, 2500);
            }
        }

        async function openContrastBuilder(targetNodeIdx = 0) {
            if (!config.getModelDraft?.()) {
                const modelPath = config.getModelPath?.();
                if (!modelPath) {
                    alertImpl('Select a Model File first.');
                    return;
                }

                try {
                    await config.loadBidsTasksForModelEditor?.();
                    const modelContent = await config.getModelContentFromPath?.(modelPath);
                    await config.loadInterestRegressorsForModelEditor?.(modelContent);
                    await config.loadGroupByOptionsForModelEditor?.();
                    config.setModelDraft?.(structuredClone(modelContent));
                } catch (error) {
                    alertImpl(`Could not load model: ${error.message}`);
                    return;
                }
            } else {
                const modelPath = config.getModelPath?.();
                if (modelPath) {
                    config.getModelContentFromPath?.(modelPath)
                        .then((modelContent) => config.loadInterestRegressorsForModelEditor?.(modelContent))
                        .catch(() => {});
                }
            }

            const nodes = getNodes();
            if (!nodes.length) {
                alertImpl('No nodes found in this model. Add a node first.');
                return;
            }

            const requestedIndex = Number(targetNodeIdx);
            cbNodeIdx = Number.isInteger(requestedIndex)
                ? Math.max(0, Math.min(requestedIndex, nodes.length - 1))
                : 0;
            reloadForNode();
            bootstrapImpl?.Modal?.getOrCreateInstance(modal)?.show();
        }

        function applyToModel() {
            const nodes = getNodes();
            if (!nodes[cbNodeIdx]) {
                showStatus('No node to apply to.', 'danger');
                return;
            }

            nodes[cbNodeIdx].Contrasts = structuredClone(cbDraft);
            if (config.getModelDraft?.()) {
                config.renderModelAccordionEditor?.();
            }
            showStatus('Applied to model! Save using "Save Model" or "Apply to Model" button.', 'success');
            if (cbStatus) {
                cbStatus.innerHTML = '<span class="text-success"><i class="fas fa-check me-1"></i>Applied. Use <strong>Model Workspace → Save Model</strong> to persist.</span>';
            }
        }

        getElement('btn-open-contrast-builder')?.addEventListener('click', () => openContrastBuilder());

        addContrastBtn?.addEventListener('click', () => {
            cbDraft.push({
                Name: defaultContrastName(),
                ConditionList: [],
                Weights: [],
                Test: 't'
            });
            renderContrastList();
        });

        addCustomBtn?.addEventListener('click', () => {
            const value = customCondInput?.value.trim();
            if (!value) return;
            if (!cbConditions.includes(value)) {
                cbConditions.push(value);
                renderConditionPool();
            }
            if (customCondInput) customCondInput.value = '';
        });

        customCondInput?.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') addCustomBtn?.click();
        });

        applyBtn?.addEventListener('click', applyToModel);

        querySelectorAll('.cb-preset-btn').forEach((button) => {
            button.addEventListener('click', () => applyPreset(button.dataset.preset));
        });

        return {
            openContrastBuilder
        };
    }

    window.BidspmAnalysisContrastBuilder = {
        createContrastBuilder
    };
})();