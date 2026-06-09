(function () {
    function createNodePanelBuilders(config = {}) {
        const fetchImpl = config.fetchImpl || window.fetch.bind(window);
        const alertImpl = config.alertImpl || window.alert.bind(window);
        const getElement = config.getElement || ((id) => document.getElementById(id));
        const getByPath = config.getByPath || (() => null);
        const getParticipantsInfo = config.getParticipantsInfo || (() => ({ sample_values: {} }));
        const normalizeStringArray = config.normalizeStringArray || ((value) => Array.isArray(value) ? value : []);
        const applyDatasetNodePreset = config.applyDatasetNodePreset || (() => ({ message: 'Applied dataset preset.', tone: 'success' }));
        const createTransformationsSchemaHint = config.createTransformationsSchemaHint || (() => null);
        const createDummyContrastsSchemaHint = config.createDummyContrastsSchemaHint || (() => null);
        const getIncomingContrastNamesForNode = config.getIncomingContrastNamesForNode || (() => []);
        const renderModelAccordionEditor = config.renderModelAccordionEditor || (() => {});
        const setModelEditorStatus = config.setModelEditorStatus || (() => {});
        const openTransformerBuilder = config.openTransformerBuilder || (() => {});
        const openContrastBuilder = config.openContrastBuilder || (() => {});

        function createPanelShell(title, helpText) {
            const panel = document.createElement('div');
            panel.className = 'd-flex flex-column gap-2 p-3 mb-2 border rounded bg-white';

            const heading = document.createElement('div');
            heading.className = 'fw-semibold';
            heading.textContent = title;
            panel.appendChild(heading);

            if (helpText) {
                const help = document.createElement('div');
                help.className = 'small text-muted';
                help.textContent = helpText;
                panel.appendChild(help);
            }

            return panel;
        }

        function createNodeMaskPicker(node) {
            const panel = document.createElement('div');
            panel.className = 'd-flex flex-wrap gap-2 align-items-center p-2 mb-2 border rounded bg-white';

            const label = document.createElement('span');
            label.className = 'small fw-bold text-muted me-1';
            label.innerHTML = '<i class="fas fa-mask me-1"></i>Brain Mask:';
            panel.appendChild(label);

            const currentDatatype = node.Mask?.datatype ?? null;
            const options = [
                { label: 'Functional (BOLD)', dt: 'func', icon: 'fa-brain' },
                { label: 'Anatomical (T1)', dt: 'anat', icon: 'fa-skull' }
            ];

            options.forEach((option) => {
                const button = document.createElement('button');
                button.type = 'button';
                const active = currentDatatype === option.dt;
                button.className = `btn btn-sm ${active ? 'btn-primary' : 'btn-outline-secondary'}`;
                button.innerHTML = `<i class="fas ${option.icon} me-1"></i>${option.label}`;
                button.addEventListener('click', () => {
                    node.Mask = { desc: 'brain', suffix: 'mask', datatype: option.dt };
                    renderModelAccordionEditor();
                });
                panel.appendChild(button);
            });

            if (node.Mask) {
                const removeBtn = document.createElement('button');
                removeBtn.type = 'button';
                removeBtn.className = 'btn btn-sm btn-outline-danger ms-1';
                removeBtn.innerHTML = '<i class="fas fa-times me-1"></i>Remove Mask';
                removeBtn.addEventListener('click', () => {
                    delete node.Mask;
                    renderModelAccordionEditor();
                });
                panel.appendChild(removeBtn);
            }

            const wdInput = getElement('input-WD');
            if (wdInput?.value) {
                const scanBtn = document.createElement('button');
                scanBtn.type = 'button';
                scanBtn.className = 'btn btn-sm btn-outline-info ms-auto';
                scanBtn.innerHTML = '<i class="fas fa-search me-1"></i>Scan';
                scanBtn.title = 'Detect available mask types from preprocessing folder';
                scanBtn.addEventListener('click', async () => {
                    scanBtn.disabled = true;
                    scanBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>';
                    try {
                        const response = await fetchImpl(`/api/scan_masks?path=${encodeURIComponent(wdInput.value)}`);
                        const masks = await response.json();
                        if (Array.isArray(masks) && masks.length) {
                            const tip = masks.map((mask) => `${mask.datatype}: ${mask.example} (${mask.count} files)`).join('\n');
                            alertImpl(`Available mask types:\n\n${tip}\n\nUse the buttons above to select one.`);
                        } else {
                            alertImpl(`No brain masks found in: ${wdInput.value}`);
                        }
                    } catch (error) {
                        alertImpl(`Scan failed: ${error.message}`);
                    }
                    scanBtn.disabled = false;
                    scanBtn.innerHTML = '<i class="fas fa-search me-1"></i>Scan';
                });
                panel.appendChild(scanBtn);
            }

            return panel;
        }

        function createAddTransformationsPanel(node) {
            const panel = createPanelShell(
                'Transformations',
                'Use Transformer Builder to create and apply pipelines. Applying a pipeline does not auto-modify the Design Matrix; generated variables become selectable for Model.X.'
            );

            const transformations = (
                node.Transformations
                && typeof node.Transformations === 'object'
                && !Array.isArray(node.Transformations)
            ) ? node.Transformations : null;

            if (!transformations) {
                const empty = document.createElement('div');
                empty.className = 'small text-muted';
                empty.textContent = 'No transformer pipeline attached yet.';
                panel.appendChild(empty);
            } else {
                const schemaHint = createTransformationsSchemaHint(transformations);
                if (schemaHint) panel.appendChild(schemaHint);

                const instructionCount = Array.isArray(transformations.Instructions) ? transformations.Instructions.length : 0;
                const explicitGenerated = normalizeStringArray(transformations.GeneratedColumns);
                const generatedWrap = document.createElement('div');
                generatedWrap.className = 'd-flex flex-wrap gap-2 align-items-center';

                const transformerBadge = document.createElement('span');
                transformerBadge.className = 'badge bg-success-subtle text-success-emphasis border';
                transformerBadge.textContent = transformations.Transformer || 'bidspm';
                generatedWrap.appendChild(transformerBadge);

                const instructionBadge = document.createElement('span');
                instructionBadge.className = 'badge bg-success-subtle text-success-emphasis border';
                instructionBadge.textContent = `${instructionCount} instruction${instructionCount === 1 ? '' : 's'}`;
                generatedWrap.appendChild(instructionBadge);

                const generatedBadge = document.createElement('span');
                generatedBadge.className = 'badge bg-warning-subtle text-warning-emphasis border';
                generatedBadge.textContent = `${explicitGenerated.length} generated`;
                generatedWrap.appendChild(generatedBadge);
                panel.appendChild(generatedWrap);

                if (explicitGenerated.length) {
                    const pills = document.createElement('div');
                    pills.className = 'd-flex flex-wrap gap-1';
                    explicitGenerated.forEach((name) => {
                        const pill = document.createElement('span');
                        pill.className = 'badge bg-secondary-subtle text-secondary-emphasis border';
                        pill.textContent = name;
                        pills.appendChild(pill);
                    });
                    panel.appendChild(pills);
                }
            }

            const actions = document.createElement('div');
            actions.className = 'd-flex flex-wrap gap-2 align-items-center';

            const builderBtn = document.createElement('button');
            builderBtn.type = 'button';
            builderBtn.className = 'btn btn-sm btn-outline-primary';
            builderBtn.innerHTML = '<i class="fas fa-wand-magic-sparkles me-1"></i>Open Transformer Builder';
            builderBtn.title = 'Open the visual Transformer Builder';
            builderBtn.addEventListener('click', () => openTransformerBuilder(String(node?.Level || '').trim()));
            actions.appendChild(builderBtn);

            if (transformations) {
                const clearBtn = document.createElement('button');
                clearBtn.type = 'button';
                clearBtn.className = 'btn btn-sm btn-outline-danger';
                clearBtn.textContent = 'Remove Transformations';
                clearBtn.addEventListener('click', () => {
                    delete node.Transformations;
                    renderModelAccordionEditor();
                    setModelEditorStatus('Transformations removed.', 'info');
                });
                actions.appendChild(clearBtn);
            }

            panel.appendChild(actions);

            return panel;
        }

        function createDummyContrastsPanel(node) {
            const panel = createPanelShell(
                'Dummy Contrasts',
                'Generate simple baseline contrasts automatically when appropriate.'
            );

            const dummyContrasts = (
                node.DummyContrasts
                && typeof node.DummyContrasts === 'object'
                && !Array.isArray(node.DummyContrasts)
            ) ? node.DummyContrasts : null;

            if (!dummyContrasts) {
                const empty = document.createElement('div');
                empty.className = 'small text-muted';
                empty.textContent = 'No dummy contrasts configured for this node.';
                panel.appendChild(empty);

                const enableBtn = document.createElement('button');
                enableBtn.type = 'button';
                enableBtn.className = 'btn btn-sm btn-outline-secondary align-self-start';
                enableBtn.textContent = 'Enable Dummy Contrasts';
                enableBtn.addEventListener('click', () => {
                    node.DummyContrasts = { Test: 't', Contrasts: [] };
                    renderModelAccordionEditor();
                    setModelEditorStatus('Dummy contrasts enabled.', 'info');
                });
                panel.appendChild(enableBtn);
                return panel;
            }

            const schemaHint = createDummyContrastsSchemaHint(dummyContrasts);
            if (schemaHint) panel.appendChild(schemaHint);

            const row = document.createElement('div');
            row.className = 'row g-2';

            const testCol = document.createElement('div');
            testCol.className = 'col-md-4';
            const testLabel = document.createElement('label');
            testLabel.className = 'form-label small mb-1';
            testLabel.textContent = 'Test';
            const testSelect = document.createElement('select');
            testSelect.className = 'form-select form-select-sm';
            ['pass', 't', 'F'].forEach((value) => {
                const option = document.createElement('option');
                option.value = value;
                option.textContent = value;
                testSelect.appendChild(option);
            });
            testSelect.value = dummyContrasts.Test || 't';
            testSelect.addEventListener('change', () => {
                dummyContrasts.Test = testSelect.value;
                setModelEditorStatus('Dummy contrasts updated.', 'info');
            });
            testCol.appendChild(testLabel);
            testCol.appendChild(testSelect);
            row.appendChild(testCol);

            const listCol = document.createElement('div');
            listCol.className = 'col-md-8';
            const listLabel = document.createElement('label');
            listLabel.className = 'form-label small mb-1';
            listLabel.textContent = 'Contrasts';
            const listInput = document.createElement('input');
            listInput.type = 'text';
            listInput.className = 'form-control form-control-sm';
            listInput.placeholder = 'trial_type.go, trial_type.stop';
            listInput.value = normalizeStringArray(dummyContrasts.Contrasts).join(', ');
            listInput.addEventListener('change', () => {
                dummyContrasts.Contrasts = String(listInput.value || '')
                    .split(',')
                    .map((value) => value.trim())
                    .filter(Boolean);
                renderModelAccordionEditor();
                setModelEditorStatus('Dummy contrasts updated.', 'info');
            });
            listCol.appendChild(listLabel);
            listCol.appendChild(listInput);
            row.appendChild(listCol);
            panel.appendChild(row);

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn btn-sm btn-outline-danger align-self-start';
            removeBtn.textContent = 'Remove Dummy Contrasts';
            removeBtn.addEventListener('click', () => {
                delete node.DummyContrasts;
                renderModelAccordionEditor();
                setModelEditorStatus('Dummy contrasts removed.', 'info');
            });
            panel.appendChild(removeBtn);

            return panel;
        }

        function createContrastManagerPanel(node, nodeIndex) {
            const panel = createPanelShell(
                'Contrasts',
                'Define named contrasts over the current node design matrix.'
            );

            const contrastCount = Array.isArray(node.Contrasts) ? node.Contrasts.length : 0;
            const incomingContrastNames = getIncomingContrastNamesForNode(nodeIndex);

            const summary = document.createElement('div');
            summary.className = 'small text-muted';
            summary.textContent = contrastCount
                ? `${contrastCount} explicit contrast${contrastCount === 1 ? '' : 's'} configured.`
                : 'No explicit contrasts defined yet.';
            panel.appendChild(summary);

            if (incomingContrastNames.length) {
                const incoming = document.createElement('div');
                incoming.className = 'small text-muted';
                incoming.textContent = `Incoming contrasts from upstream nodes: ${incomingContrastNames.join(', ')}`;
                panel.appendChild(incoming);
            }

            const actions = document.createElement('div');
            actions.className = 'd-flex flex-wrap gap-2 align-items-center';

            const openBtn = document.createElement('button');
            openBtn.type = 'button';
            openBtn.className = 'btn btn-sm btn-outline-primary';
            openBtn.innerHTML = '<i class="fas fa-puzzle-piece me-1"></i>Open Contrast Manager';
            openBtn.addEventListener('click', () => openContrastBuilder(nodeIndex));
            actions.appendChild(openBtn);

            if (contrastCount) {
                const clearBtn = document.createElement('button');
                clearBtn.type = 'button';
                clearBtn.className = 'btn btn-sm btn-outline-danger';
                clearBtn.textContent = 'Clear Contrasts';
                clearBtn.addEventListener('click', () => {
                    node.Contrasts = [];
                    renderModelAccordionEditor();
                    setModelEditorStatus('Contrasts cleared.', 'info');
                });
                actions.appendChild(clearBtn);
            }

            panel.appendChild(actions);

            return panel;
        }

        function createDatasetModelPresetPanel(basePath) {
            const match = String(basePath || '').match(/^Nodes\[(\d+)\]\.Model$/);
            if (!match) return null;

            const nodePath = `Nodes[${match[1]}]`;
            const node = getByPath(nodePath);
            if (!node || typeof node !== 'object' || String(node.Level || '').trim() !== 'Dataset') {
                return null;
            }

            const panel = document.createElement('div');
            panel.className = 'd-flex flex-column gap-3 p-3 mb-2 border rounded bg-white';

            const participantsInfo = getParticipantsInfo();
            const categoricalColumns = normalizeStringArray(participantsInfo.categorical_columns);
            const numericColumns = normalizeStringArray(participantsInfo.numeric_columns);
            const sampleValues = (participantsInfo.sample_values && typeof participantsInfo.sample_values === 'object')
                ? participantsInfo.sample_values
                : {};

            if (!node.Model || typeof node.Model !== 'object' || Array.isArray(node.Model)) {
                node.Model = { Type: 'glm', X: ['1'] };
            }
            if (!Array.isArray(node.Model.X)) node.Model.X = [];
            node.Model.X = normalizeStringArray(node.Model.X);
            if (!node.Model.X.length) node.Model.X = ['1'];

            function createFieldRow(labelText) {
                const row = document.createElement('div');
                row.className = 'd-flex flex-column gap-1';
                const label = document.createElement('label');
                label.className = 'form-label small mb-0';
                label.textContent = labelText;
                row.appendChild(label);
                return { row, label };
            }

            function rerender(message, tone = 'info') {
                renderModelAccordionEditor();
                setModelEditorStatus(message, tone);
            }

            const title = document.createElement('div');
            title.className = 'small fw-bold text-muted';
            title.innerHTML = '<i class="fas fa-wave-square me-1"></i>Second-Level Presets';
            panel.appendChild(title);

            const help = document.createElement('div');
            help.className = 'small text-muted';
            help.innerHTML = 'Dataset-level nodes use <strong>participants.tsv</strong> variables for grouping and covariates. Pick a preset, then refine <strong>Contrasts</strong> and <strong>Edges.Filter.contrast</strong> if needed.';
            panel.appendChild(help);

            const presetRow = createFieldRow('Preset');
            const presetSelect = document.createElement('select');
            presetSelect.className = 'form-select form-select-sm';
            [
                ['one_sample_all', 'one sample t-test: all subjects'],
                ['one_sample_by_group', 'one sample t-test: one model per group'],
                ['two_sample_groups', '2 samples t-test: compare 2 groups'],
                ['one_way_anova', 'one way ANOVA: compare several groups'],
                ['linear_regression', 'linear regression: numeric covariate']
            ].forEach(([value, label]) => {
                const option = document.createElement('option');
                option.value = value;
                option.textContent = label;
                presetSelect.appendChild(option);
            });
            presetRow.row.appendChild(presetSelect);
            panel.appendChild(presetRow.row);

            const defaultGroupVar = node.GroupBy.find((value) => categoricalColumns.includes(String(value)))
                || node.Model.X.find((value) => categoricalColumns.includes(String(value)))
                || categoricalColumns[0]
                || '';
            const defaultCovariate = node.Model.X.find((value) => numericColumns.includes(String(value)))
                || numericColumns[0]
                || '';

            const groupVarRow = createFieldRow('Grouping Variable');
            const groupVarSelect = document.createElement('select');
            groupVarSelect.className = 'form-select form-select-sm';
            const emptyGroupOption = document.createElement('option');
            emptyGroupOption.value = '';
            emptyGroupOption.textContent = categoricalColumns.length ? 'Select participant column' : 'No categorical participant columns found';
            groupVarSelect.appendChild(emptyGroupOption);
            categoricalColumns.forEach((column) => {
                const option = document.createElement('option');
                option.value = column;
                option.textContent = column;
                groupVarSelect.appendChild(option);
            });
            groupVarSelect.value = defaultGroupVar;
            groupVarRow.row.appendChild(groupVarSelect);
            panel.appendChild(groupVarRow.row);

            const covariateRow = createFieldRow('Numeric Covariate');
            const covariateSelect = document.createElement('select');
            covariateSelect.className = 'form-select form-select-sm';
            const emptyCovariateOption = document.createElement('option');
            emptyCovariateOption.value = '';
            emptyCovariateOption.textContent = numericColumns.length ? 'Select numeric participant column' : 'No numeric participant columns found';
            covariateSelect.appendChild(emptyCovariateOption);
            numericColumns.forEach((column) => {
                const option = document.createElement('option');
                option.value = column;
                option.textContent = column;
                covariateSelect.appendChild(option);
            });
            covariateSelect.value = defaultCovariate;
            covariateRow.row.appendChild(covariateSelect);
            panel.appendChild(covariateRow.row);

            const groupARow = createFieldRow('Group A');
            const groupASelect = document.createElement('select');
            groupASelect.className = 'form-select form-select-sm';
            groupARow.row.appendChild(groupASelect);
            panel.appendChild(groupARow.row);

            const groupBRow = createFieldRow('Group B');
            const groupBSelect = document.createElement('select');
            groupBSelect.className = 'form-select form-select-sm';
            groupBRow.row.appendChild(groupBSelect);
            panel.appendChild(groupBRow.row);

            const valuesHint = document.createElement('div');
            valuesHint.className = 'small text-muted';
            panel.appendChild(valuesHint);

            function updateGroupLevelOptions() {
                const groupVariable = groupVarSelect.value;
                const levels = normalizeStringArray(sampleValues[groupVariable]);
                groupASelect.innerHTML = '';
                groupBSelect.innerHTML = '';

                if (!levels.length) {
                    const emptyA = document.createElement('option');
                    emptyA.value = '';
                    emptyA.textContent = 'No sample values found';
                    const emptyB = emptyA.cloneNode(true);
                    groupASelect.appendChild(emptyA);
                    groupBSelect.appendChild(emptyB);
                    valuesHint.textContent = groupVariable
                        ? `No sample values were found for ${groupVariable}.`
                        : 'Pick a grouping variable to inspect its observed values.';
                    return;
                }

                levels.forEach((level) => {
                    const optionA = document.createElement('option');
                    optionA.value = level;
                    optionA.textContent = level;
                    groupASelect.appendChild(optionA);

                    const optionB = document.createElement('option');
                    optionB.value = level;
                    optionB.textContent = level;
                    groupBSelect.appendChild(optionB);
                });

                groupASelect.value = levels[0] || '';
                groupBSelect.value = levels[1] || levels[0] || '';
                valuesHint.textContent = `${groupVariable} values: ${levels.join(', ')}`;
            }

            function updatePresetVisibility() {
                const preset = presetSelect.value;
                const needsGrouping = ['one_sample_by_group', 'two_sample_groups', 'one_way_anova'].includes(preset);
                const needsTwoGroups = preset === 'two_sample_groups';
                const needsCovariate = preset === 'linear_regression';
                groupVarRow.row.style.display = needsGrouping ? 'flex' : 'none';
                groupARow.row.style.display = needsTwoGroups ? 'flex' : 'none';
                groupBRow.row.style.display = needsTwoGroups ? 'flex' : 'none';
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
            applyPresetBtn.addEventListener('click', () => {
                const result = applyDatasetNodePreset(node, presetSelect.value, {
                    groupVariable: groupVarSelect.value.trim(),
                    covariate: covariateSelect.value.trim(),
                    groupA: groupASelect.value.trim(),
                    groupB: groupBSelect.value.trim()
                });
                rerender(result.message, result.tone || 'success');
            });
            panel.appendChild(applyPresetBtn);

            const participantsCard = document.createElement('div');
            participantsCard.className = 'border rounded p-2 bg-light-subtle d-flex flex-column gap-1';
            const participantsTitle = document.createElement('div');
            participantsTitle.className = 'small fw-bold';
            participantsTitle.textContent = 'participants.tsv Variables';
            participantsCard.appendChild(participantsTitle);

            const participantsHint = document.createElement('div');
            participantsHint.className = 'small text-muted';
            participantsHint.textContent = participantsInfo.sample_status === 'present'
                ? 'Categorical variables are useful for groups. Numeric variables can be used as covariates in Model.X.'
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
            panel.appendChild(participantsCard);

            return panel;
        }

        return {
            createAddTransformationsPanel,
            createContrastManagerPanel,
            createDatasetModelPresetPanel,
            createDummyContrastsPanel,
            createNodeMaskPicker
        };
    }

    window.BidspmAnalysisNodePanels = {
        createNodePanelBuilders
    };
})();