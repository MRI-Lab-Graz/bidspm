// analysis_nuisance_picker.js
// Extracted from templates/analysis.html — nuisance regressor picker helpers.
// Global functions. Relies on globals: normalizeStringArray, modelEditorInterestRegressors (defined in analysis.html inline script as var).

    function extendInterestRegressorPool(names) {
        const additions = normalizeStringArray(names);
        if (!additions.length) return;
        modelEditorInterestRegressors = Array.from(new Set([...modelEditorInterestRegressors, ...additions]));
    }

    var NUISANCE_REGRESSOR_RX = /^(framewise_displacement|trans_[xyz]|rot_[xyz]|a_comp_cor|dvars|std_dvars|non_steady_state_outlier|cosine\d*|white_matter|csf|global_signal)/;

    const CONFOUND_GROUP_DEFS = [
        { id: 'motion6',           label: '6 motion (trans/rot)',           match: (n) => /^(trans|rot)_[xyz]$/.test(n) },
        { id: 'motion_deriv',      label: 'Motion derivatives',             match: (n) => /^(trans|rot)_[xyz]_derivative1$/.test(n) },
        { id: 'motion_sq',         label: 'Motion squared',                 match: (n) => /^(trans|rot)_[xyz]_power2$/.test(n) },
        { id: 'motion_deriv_sq',   label: 'Motion derivative squared',      match: (n) => /^(trans|rot)_[xyz]_derivative1_power2$/.test(n) },
        { id: 'fd',                label: 'Framewise displacement / RMSD',  match: (n) => /^(framewise_displacement|rmsd)$/.test(n) },
        { id: 'dvars',             label: 'DVARS',                          match: (n) => /^(dvars|std_dvars)$/.test(n) },
        { id: 'acompcor',          label: 'aCompCor',                       match: (n) => /^a_comp_cor_/.test(n) },
        { id: 'tcompcor',          label: 'tCompCor',                       match: (n) => /^t_comp_cor_/.test(n) },
        { id: 'wcompcor',          label: 'WM CompCor',                     match: (n) => /^w_comp_cor_/.test(n) },
        { id: 'ccompcor',          label: 'CSF CompCor',                    match: (n) => /^c_comp_cor_/.test(n) },
        { id: 'cosine',            label: 'Cosine (drift)',                  match: (n) => /^cosine\d+$/.test(n) },
        { id: 'motion_outlier',    label: 'Motion outliers',                match: (n) => /^motion_outlier\d+$/.test(n) },
        { id: 'nss',               label: 'Non-steady-state outliers',      match: (n) => /^non_steady_state_outlier\d+$/.test(n) },
        { id: 'tissue',            label: 'Tissue signals (WM/CSF/global)', match: (n) => /^(white_matter|csf|global_signal)$/.test(n) },
        { id: 'tissue_dx',         label: 'Tissue derivatives / squared',   match: (n) => /^(white_matter|csf|global_signal)_(derivative1|power2|derivative1_power2)$/.test(n) },
        { id: 'other',             label: 'Other',                          match: () => true }
    ];

    function groupConfoundColumns(columns) {
        const groups = new Map(CONFOUND_GROUP_DEFS.map(def => [def.id, { def, items: [] }]));
        (columns || []).forEach(col => {
            const name = String(col || '').trim();
            if (!name) return;
            for (const def of CONFOUND_GROUP_DEFS) {
                if (def.match(name)) { groups.get(def.id).items.push(name); break; }
            }
        });
        groups.forEach(entry => {
            entry.items.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
        });
        return groups;
    }

    function buildNuisanceRegressorPicker({ confoundColumns, curatedColumns, getSelectedSet, onAdd, onRemove }) {
        const root = document.createElement('div');
        root.className = 'd-flex flex-column gap-2';

        const columns = Array.isArray(confoundColumns) ? confoundColumns : [];
        const groups = groupConfoundColumns(columns);
        const selectedSet = () => (typeof getSelectedSet === 'function' ? getSelectedSet() : null) || new Set();

        const presetBar = document.createElement('div');
        presetBar.className = 'd-flex flex-wrap gap-1';
        const itemsOf = (id) => (groups.get(id)?.items || []);
        const presets = [
            { label: '6 motion',               cols: itemsOf('motion6') },
            { label: '12 motion (+deriv)',      cols: [...itemsOf('motion6'), ...itemsOf('motion_deriv')] },
            { label: '24 motion (Friston)',     cols: [...itemsOf('motion6'), ...itemsOf('motion_deriv'), ...itemsOf('motion_sq'), ...itemsOf('motion_deriv_sq')] },
            { label: 'aCompCor top 5',          cols: itemsOf('acompcor').slice(0, 5) },
            { label: 'Cosines (drift)',          cols: itemsOf('cosine') },
            { label: 'FD + DVARS',              cols: [...itemsOf('fd'), ...itemsOf('dvars')] },
            { label: 'Outliers (motion+NSS)',   cols: [...itemsOf('motion_outlier'), ...itemsOf('nss')] },
            { label: 'Tissue (WM/CSF/global)',  cols: itemsOf('tissue') }
        ];
        presets.forEach(preset => {
            if (!preset.cols.length) return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm btn-outline-primary py-0 px-2';
            btn.textContent = `${preset.label} (+${preset.cols.length})`;
            btn.title = `Add: ${preset.cols.join(', ')}`;
            btn.addEventListener('click', () => preset.cols.forEach(col => onAdd && onAdd(col)));
            presetBar.appendChild(btn);
        });
        if (presetBar.childElementCount) root.appendChild(presetBar);

        const filterInput = document.createElement('input');
        filterInput.type = 'search';
        filterInput.className = 'form-control form-control-sm';
        filterInput.placeholder = columns.length
            ? `Filter ${columns.length} confound column${columns.length === 1 ? '' : 's'}…`
            : 'No confound columns discovered yet';
        if (!columns.length) filterInput.disabled = true;
        root.appendChild(filterInput);

        const list = document.createElement('div');
        list.className = 'd-flex flex-column gap-1';
        root.appendChild(list);

        function renderGroups(query) {
            list.innerHTML = '';
            const q = String(query || '').trim().toLowerCase();
            const sel = selectedSet();
            let totalShown = 0;
            CONFOUND_GROUP_DEFS.forEach(def => {
                const all = groups.get(def.id)?.items || [];
                const items = q ? all.filter(name => name.toLowerCase().includes(q)) : all;
                if (!items.length) return;
                totalShown += items.length;

                const block = document.createElement('details');
                block.className = 'border rounded p-1';
                block.open = Boolean(q) || ['motion6', 'fd', 'dvars'].includes(def.id);

                const summary = document.createElement('summary');
                summary.className = 'small fw-semibold d-flex align-items-center gap-2';
                summary.style.cursor = 'pointer';

                const label = document.createElement('span');
                label.textContent = `${def.label} (${items.length})`;
                summary.appendChild(label);

                const addAll = document.createElement('button');
                addAll.type = 'button';
                addAll.className = 'btn btn-sm btn-outline-secondary py-0 px-1 ms-auto';
                addAll.textContent = '+ all';
                addAll.title = `Add all ${items.length} ${def.label} regressors to Model.X`;
                addAll.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    items.forEach(col => onAdd && onAdd(col));
                });
                summary.appendChild(addAll);

                const removeAll = document.createElement('button');
                removeAll.type = 'button';
                removeAll.className = 'btn btn-sm btn-outline-secondary py-0 px-1';
                removeAll.textContent = '– all';
                removeAll.title = `Remove all ${def.label} regressors from Model.X`;
                removeAll.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    items.forEach(col => onRemove && onRemove(col));
                });
                summary.appendChild(removeAll);

                block.appendChild(summary);

                const grid = document.createElement('div');
                grid.className = 'modelx-pool mt-1';
                items.forEach(col => {
                    const isSelected = sel.has(col);
                    const badge = document.createElement('button');
                    badge.type = 'button';
                    badge.className = isSelected
                        ? 'btn btn-sm btn-secondary modelx-reg-badge'
                        : 'btn btn-sm btn-outline-secondary modelx-reg-badge';
                    badge.textContent = col;
                    badge.draggable = !isSelected;
                    badge.title = isSelected ? 'Already in Model.X — click to remove' : 'Click to add to Model.X';
                    badge.addEventListener('click', () => {
                        if (selectedSet().has(col)) {
                            if (onRemove) onRemove(col);
                        } else if (onAdd) {
                            onAdd(col);
                        }
                    });
                    badge.addEventListener('dragstart', (event) => {
                        event.dataTransfer.effectAllowed = 'copy';
                        event.dataTransfer.setData('application/x-modelx-regressor', col);
                        event.dataTransfer.setData('text/plain', col);
                    });
                    grid.appendChild(badge);
                });
                block.appendChild(grid);
                list.appendChild(block);
            });

            if (!totalShown) {
                const empty = document.createElement('div');
                empty.className = 'small text-muted';
                empty.textContent = columns.length
                    ? 'No confound columns match the filter.'
                    : 'No confound columns discovered. Set the fMRIPrep folder and reload.';
                list.appendChild(empty);
            }
        }

        filterInput.addEventListener('input', () => renderGroups(filterInput.value));
        renderGroups('');

        const missingCurated = (curatedColumns || []).filter(col => !columns.includes(col));
        if (missingCurated.length) {
            const warn = document.createElement('div');
            warn.className = 'small text-warning';
            warn.textContent = `Heads up: ${missingCurated.join(', ')} not present in current confounds file(s).`;
            root.appendChild(warn);
        }

        return root;
    }
