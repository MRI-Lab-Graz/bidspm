(function () {
    function emptyParticipantsInfo() {
        return {
            columns: [],
            categorical_columns: [],
            numeric_columns: [],
            sample_values: {},
            numeric_stats: {},
            sample_status: 'missing-dir'
        };
    }

    function normalizeStringArray(value) {
        if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
        if (value === undefined || value === null || typeof value === 'object') return [];
        const normalized = String(value).trim();
        return normalized ? [normalized] : [];
    }

    function createModelHelperApi(config = {}) {
        const getModelDraft = config.getModelDraft || (() => null);
        const getInterestRegressors = config.getInterestRegressors || (() => []);
        const getParticipantsInfo = config.getParticipantsInfo || emptyParticipantsInfo;
        const getInputEntityValues = config.getInputEntityValues || (() => ({}));
        const getEventSamples = config.getEventSamples || (() => ({ trial_type: [], condition: [] }));

        function slugifyNodeToken(value) {
            return String(value || '')
                .trim()
                .replace(/\s+/g, '_')
                .replace(/[^A-Za-z0-9_]+/g, '_')
                .replace(/^_+|_+$/g, '')
                .toLowerCase();
        }

        function getUniqueModelNodeName(baseName) {
            const normalizedBase = String(baseName || '').trim() || 'node';
            const draft = getModelDraft();
            const existing = new Set(
                (Array.isArray(draft?.Nodes) ? draft.Nodes : [])
                    .map((node) => String(node?.Name || '').trim().toLowerCase())
                    .filter(Boolean)
            );
            if (!existing.has(normalizedBase.toLowerCase())) return normalizedBase;
            for (let index = 2; index < 1000; index += 1) {
                const candidate = `${normalizedBase}_${index}`;
                if (!existing.has(candidate.toLowerCase())) return candidate;
            }
            return `${normalizedBase}_${Date.now().toString().slice(-4)}`;
        }

        function getTransformerModelXRegressorsForNode(node) {
            const transformations = (node?.Transformations && typeof node.Transformations === 'object' && !Array.isArray(node.Transformations))
                ? node.Transformations
                : null;

            // The actual domain-propagation (Filter, Replace, Copy, Concatenate, Factor, ...)
            // lives in transformer_model_x_domains.js so this stays in sync with the
            // Transformer Builder's own "Generated Columns" preview instead of drifting
            // out of sync as a second, partial reimplementation.
            const seedSamples = getEventSamples() || { trial_type: [], condition: [] };
            const seedDomains = {
                trial_type: normalizeStringArray(seedSamples.trial_type),
                condition: normalizeStringArray(seedSamples.condition)
            };

            return window.TransformerModelXDomains.getModelXRegressors(seedDomains, transformations);
        }

        function getModelNodeByName(nodeName) {
            const normalizedName = String(nodeName || '').trim();
            if (!normalizedName) return null;
            const draft = getModelDraft();
            const nodes = Array.isArray(draft?.Nodes) ? draft.Nodes : [];
            return nodes.find((node) => String(node?.Name || '').trim() === normalizedName) || null;
        }

        function getNodeOutputContrastNames(node) {
            if (!node || typeof node !== 'object') return [];
            const explicitNames = Array.isArray(node.Contrasts)
                ? node.Contrasts.map((contrast) => String(contrast?.Name || '').trim()).filter(Boolean)
                : [];
            const dummyNames = normalizeStringArray(node.DummyContrasts?.Contrasts);
            return Array.from(new Set([...explicitNames, ...dummyNames]));
        }

        function getEdgeAvailableContrastNames(edge) {
            return getNodeOutputContrastNames(getModelNodeByName(edge?.Source));
        }

        // bidspm auto-replicates a Run-level Contrast/DummyContrast once per run/session,
        // naming each copy "<name>_ses-<ses>_run-<run>" (see constructContrastNameFromBidsEntity.m).
        // A downstream node never sees the bare "<name>" as an actual regressor — only these
        // concrete per-run/session names exist in the SPM design — so expand bare contrast
        // names accordingly using the dataset's known run/session labels before suggesting them.
        function expandUpstreamContrastNames(names, sourceNode) {
            const bareNames = Array.from(new Set(normalizeStringArray(names)));
            if (!bareNames.length) return bareNames;
            if (String(sourceNode?.Level || '').trim().toLowerCase() !== 'run') return bareNames;

            const groupBy = normalizeStringArray(sourceNode.GroupBy).map((v) => v.toLowerCase());
            const entityValues = getInputEntityValues() || {};
            const sessions = normalizeStringArray(entityValues.session);
            const runs = groupBy.includes('run') ? normalizeStringArray(entityValues.run) : [];

            if (!runs.length && !sessions.length) return bareNames;

            const expanded = [];
            bareNames.forEach((name) => {
                if (runs.length && sessions.length) {
                    runs.forEach((run) => sessions.forEach((ses) => expanded.push(`${name}_ses-${ses}_run-${run}`)));
                } else if (runs.length) {
                    runs.forEach((run) => expanded.push(`${name}_run-${run}`));
                } else {
                    sessions.forEach((ses) => expanded.push(`${name}_ses-${ses}`));
                }
            });
            return Array.from(new Set(expanded));
        }

        function getIncomingContrastNamesForNode(nodeIdx) {
            const draft = getModelDraft();
            const nodes = Array.isArray(draft?.Nodes) ? draft.Nodes : [];
            const node = nodes[nodeIdx];
            const destinationName = String(node?.Name || '').trim();
            if (!destinationName) return [];

            const edges = Array.isArray(draft?.Edges) ? draft.Edges : [];
            const incoming = [];
            edges.forEach((edge) => {
                if (String(edge?.Destination || '').trim() !== destinationName) return;
                const sourceNode = getModelNodeByName(edge?.Source);
                const availableFromSource = getNodeOutputContrastNames(sourceNode);
                const filterValues = normalizeStringArray(edge?.Filter?.contrast);
                const selected = filterValues.length
                    ? availableFromSource.filter((name) => filterValues.includes(name))
                    : availableFromSource;
                expandUpstreamContrastNames(selected, sourceNode).forEach((name) => incoming.push(name));
            });

            if (!incoming.length && nodeIdx > 0) {
                const sourceNode = nodes[nodeIdx - 1];
                expandUpstreamContrastNames(getNodeOutputContrastNames(sourceNode), sourceNode).forEach((name) => incoming.push(name));
            }

            return Array.from(new Set(incoming));
        }

        function getParticipantRegressorTerms(includeIntercept = true) {
            const participantsInfo = getParticipantsInfo();
            const categoricalColumns = normalizeStringArray(participantsInfo.categorical_columns);
            const numericColumns = normalizeStringArray(participantsInfo.numeric_columns);
            const baseTerms = includeIntercept ? ['1'] : [];
            return Array.from(new Set([...baseTerms, ...categoricalColumns, ...numericColumns])).filter(Boolean);
        }

        function isFirstLevelNodeIndex(nodeIdx) {
            return Number(nodeIdx) === 0;
        }

        function getHigherLevelMetadataTerms(node) {
            return Array.from(new Set(
                normalizeStringArray(node?.GroupBy)
                    .filter((term) => term && term !== 'contrast')
            )).filter(Boolean);
        }

        function getFactorLevelTermsForNode(nodeIdx) {
            const draft = getModelDraft();
            const nodes = Array.isArray(draft?.Nodes) ? draft.Nodes : [];
            const node = nodes[nodeIdx] || {};
            const participantsInfo = getParticipantsInfo();
            const participantSampleValues = (participantsInfo.sample_values && typeof participantsInfo.sample_values === 'object')
                ? participantsInfo.sample_values
                : {};
            const inputEntityValues = getInputEntityValues() || {};
            const metadataTerms = getHigherLevelMetadataTerms(node);
            const expanded = [];

            metadataTerms.forEach((term) => {
                const inputLevels = normalizeStringArray(inputEntityValues[term]);
                const participantLevels = normalizeStringArray(participantSampleValues[term]);
                Array.from(new Set([...inputLevels, ...participantLevels])).forEach((level) => {
                    expanded.push(`${term}.${level}`);
                });
            });

            return Array.from(new Set(expanded)).filter(Boolean);
        }

        function getHigherLevelRegressorTermsForNode(nodeIdx, includeIntercept = true) {
            const draft = getModelDraft();
            const nodes = Array.isArray(draft?.Nodes) ? draft.Nodes : [];
            const node = nodes[nodeIdx] || {};
            const baseTerms = includeIntercept ? ['1'] : [];
            return Array.from(new Set([
                ...baseTerms,
                ...getHigherLevelMetadataTerms(node),
                ...getParticipantRegressorTerms(false),
                ...getIncomingContrastNamesForNode(nodeIdx)
            ])).filter(Boolean);
        }

        function getSuggestedModelTermsForNode(nodeIdx) {
            const draft = getModelDraft();
            const nodes = Array.isArray(draft?.Nodes) ? draft.Nodes : [];
            const node = nodes[nodeIdx] || {};
            const level = String(node?.Level || '').trim().toLowerCase();
            // bidspm only ever executes Transformations for Run-level events.tsv data, so
            // suggesting transformer-generated regressors at other levels would be misleading.
            const transformerRegressors = level === 'run' ? getTransformerModelXRegressorsForNode(node) : [];

            if (level === 'dataset') {
                return getParticipantRegressorTerms(true);
            }

            if (isFirstLevelNodeIndex(nodeIdx)) {
                return Array.from(new Set([
                    ...normalizeStringArray(getInterestRegressors()),
                    ...transformerRegressors
                ])).filter(Boolean);
            }

            return Array.from(new Set([
                ...getHigherLevelRegressorTermsForNode(nodeIdx, true),
                ...transformerRegressors
            ])).filter(Boolean);
        }

        function getSuggestedConditionTermsForNode(nodeIdx) {
            const draft = getModelDraft();
            const nodes = Array.isArray(draft?.Nodes) ? draft.Nodes : [];
            const node = nodes[nodeIdx] || {};
            const incomingContrasts = getIncomingContrastNamesForNode(nodeIdx);
            const modelTerms = normalizeStringArray(node.Model?.X).filter((term) => term !== '1');
            const localFallback = getSuggestedModelTermsForNode(nodeIdx).filter((term) => term !== '1');
            const factorLevels = getFactorLevelTermsForNode(nodeIdx);
            return Array.from(new Set([...incomingContrasts, ...modelTerms, ...localFallback, ...factorLevels]));
        }

        function getDefaultConditionTokenForPath(path) {
            const match = String(path || '').match(/^Nodes\[(\d+)\]\./);
            if (!match) return 'trial_type.active';
            const nodeIdx = Number(match[1]);
            const suggestions = getSuggestedConditionTermsForNode(nodeIdx);
            return suggestions[0] || 'trial_type.active';
        }

        function applyDatasetNodePreset(node, preset, options = {}) {
            const participantsInfo = getParticipantsInfo();
            const categoricalColumns = normalizeStringArray(participantsInfo.categorical_columns);
            const numericColumns = normalizeStringArray(participantsInfo.numeric_columns);
            const sampleValues = (participantsInfo.sample_values && typeof participantsInfo.sample_values === 'object')
                ? participantsInfo.sample_values
                : {};

            const groupVariable = String(options.groupVariable || categoricalColumns[0] || '').trim();
            const covariate = String(options.covariate || numericColumns[0] || '').trim();
            const allLevels = normalizeStringArray(sampleValues[groupVariable]);
            const groupA = String(options.groupA || allLevels[0] || '').trim();
            const groupB = String(options.groupB || allLevels.find((level) => level !== groupA) || allLevels[0] || '').trim();

            node.Level = 'Dataset';
            if (!node.Model || typeof node.Model !== 'object' || Array.isArray(node.Model)) {
                node.Model = {};
            }
            node.Model = {
                ...node.Model,
                Type: String(node.Model.Type || 'glm').trim() || 'glm',
                X: ['1']
            };
            delete node.Model.HRF;
            delete node.Transformations;

            if (preset === 'one_sample_all') {
                node.GroupBy = ['contrast'];
                node.Description = 'one sample t-test: averaging across all subjects';
                node.DummyContrasts = { Test: 't' };
                node.Contrasts = [];
                return { message: 'Applied all-subject one-sample dataset preset.', tone: 'success', suggestedName: 'dataset_level' };
            }

            if (preset === 'one_sample_by_group') {
                node.GroupBy = groupVariable ? ['contrast', groupVariable] : ['contrast'];
                node.Description = groupVariable
                    ? `one sample t-test for each ${groupVariable} group`
                    : 'one sample t-test for each group';
                node.DummyContrasts = { Test: 't' };
                node.Contrasts = [];
                return {
                    message: groupVariable
                        ? `Applied one-sample-by-group preset using ${groupVariable}.`
                        : 'Added one-sample-by-group scaffold. Select a participants.tsv grouping variable to finish setup.',
                    tone: groupVariable ? 'success' : 'warning',
                    suggestedName: groupVariable ? `within_${slugifyNodeToken(groupVariable)}_group` : 'within_group'
                };
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
                }
                return {
                    message: groupVariable
                        ? `Applied two-sample group comparison using ${groupVariable}.`
                        : 'Added two-sample scaffold. Select a categorical participants.tsv variable to finish setup.',
                    tone: groupVariable ? 'success' : 'warning',
                    suggestedName: groupVariable ? `between_${slugifyNodeToken(groupVariable)}_groups` : 'between_groups'
                };
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
                        ConditionList: allLevels.map((level) => `${groupVariable}.${level}`),
                        Weights: allLevels.map(() => 1),
                        Test: 't'
                    }];
                }
                return {
                    message: groupVariable
                        ? `Applied one-way ANOVA scaffold using ${groupVariable}.`
                        : 'Added one-way ANOVA scaffold. Select a categorical participants.tsv variable to finish setup.',
                    tone: groupVariable ? 'success' : 'warning',
                    suggestedName: groupVariable ? `${slugifyNodeToken(groupVariable)}_anova` : 'one_way_anova'
                };
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
                }
                return {
                    message: covariate
                        ? `Applied linear regression preset using ${covariate}.`
                        : 'Added linear regression scaffold. Select a numeric participants.tsv covariate to finish setup.',
                    tone: covariate ? 'success' : 'warning',
                    suggestedName: covariate ? `${slugifyNodeToken(covariate)}_regression` : 'dataset_regression'
                };
            }

            return { message: 'Applied dataset preset.', tone: 'success', suggestedName: 'dataset_level' };
        }

        function buildNodeFromPreset(preset) {
            if (preset === 'session_basic') {
                return {
                    node: {
                        Level: 'Session',
                        Name: getUniqueModelNodeName('session_level'),
                        GroupBy: ['contrast', 'session', 'subject'],
                        Model: { Type: 'glm', X: ['1'] },
                        DummyContrasts: { Test: 't' },
                        Contrasts: []
                    },
                    message: 'Added session-level node.',
                    tone: 'success'
                };
            }

            if (preset === 'subject_fixed') {
                return {
                    node: {
                        Level: 'Subject',
                        Name: getUniqueModelNodeName('subject_level'),
                        GroupBy: ['contrast', 'subject'],
                        Model: { Type: 'glm', X: ['1'] },
                        DummyContrasts: { Test: 't' },
                        Contrasts: []
                    },
                    message: 'Added subject-level fixed-effects node.',
                    tone: 'success'
                };
            }

            if (preset === 'dataset_basic') {
                return {
                    node: {
                        Level: 'Dataset',
                        Name: getUniqueModelNodeName('dataset_level'),
                        GroupBy: ['contrast'],
                        Model: { Type: 'glm', X: ['1'] },
                        DummyContrasts: { Test: 't' },
                        Contrasts: []
                    },
                    message: 'Added dataset-level node. Configure second-level preset in Node.Model.',
                    tone: 'success'
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
                node.Name = getUniqueModelNodeName(result.suggestedName || 'dataset_level');
                return { node, message: result.message, tone: result.tone || 'success' };
            }

            const draft = getModelDraft();
            const existingNodeCount = Array.isArray(draft?.Nodes) ? draft.Nodes.length : 0;

            if (existingNodeCount > 0) {
                return {
                    node: {
                        Level: 'Subject',
                        Name: getUniqueModelNodeName('subject_level'),
                        GroupBy: ['contrast', 'subject'],
                        Model: { Type: 'glm', X: ['1'] },
                        DummyContrasts: { Test: 't' },
                        Contrasts: []
                    },
                    message: 'Added higher-level node.',
                    tone: 'success'
                };
            }

            return {
                node: {
                    Level: 'Run',
                    Name: getUniqueModelNodeName('run_level'),
                    GroupBy: ['run', 'subject'],
                    Model: {
                        X: ['trial_type'],
                        HRF: { Variables: ['trial_type'], Model: 'spm' },
                        Type: 'glm',
                        Software: { SPM: { Model: 'spm' } }
                    },
                    Contrasts: []
                },
                message: 'Added run-level node.',
                tone: 'success'
            };
        }

        return {
            applyDatasetNodePreset,
            buildNodeFromPreset,
            getDefaultConditionTokenForPath,
            getIncomingContrastNamesForNode,
            getSuggestedModelTermsForNode,
            getSuggestedConditionTermsForNode,
            getTransformerModelXRegressorsForNode
        };
    }

    window.BidspmAnalysisModelPresets = {
        createModelHelperApi,
        emptyParticipantsInfo,
        normalizeStringArray
    };
})();