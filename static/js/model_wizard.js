// model_wizard.js -- renders the wizard form and collects choices. All logic lives in lib/model_wizard.py
// (/api/wizard/scan, /api/wizard/build). Server strings go in via textContent/DOM nodes, never innerHTML.
const WIZ = window.BIDSPM_WIZARD_CONTEXT;
const wiz = {scan: null, preview: null, recipes: [], pairs: [], timer: null, seq: 0, pathEdited: false};
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...kids) {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...kids);
    return node;
}

function option(value, label) { return el('option', {value, textContent: label ?? value}); }

async function postJson(url, body) {
    const res = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    let data;
    try { data = await res.json(); } catch (e) { throw new Error(`HTTP ${res.status}`); }
    return {status: res.status, data};
}

function showError(msg) {
    $('wiz-error').textContent = msg || '';
    $('wiz-error').hidden = !msg;
}

// ---- choices ----------------------------------------------------------------------------------
function excluded() {
    return [...$('wiz-conditions').querySelectorAll('input:not(:checked)')].map((i) => i.value);
}

function nuisanceChoice() {
    const v = $('wiz-nuisance').value;
    if (v !== 'custom') return v;
    return $('wiz-nuisance-custom').value.split(',').map((s) => s.trim()).filter(Boolean);
}

function collectChoices() {
    return {
        task: $('wiz-task').value, name: $('wiz-name').value.trim(), exclude: excluded(),
        recipes: wiz.recipes.map((r) => ({id: r.id, ...r.params})),
        nuisance: nuisanceChoice(),
        contrasts: {auto: $('wiz-auto-contrasts').checked, pairs: wiz.pairs.filter((p) => p.positive.length && p.negative.length)},
    };
}

function requestBody(extra = {}) {
    return {choices: collectChoices(), bids_dir: WIZ.bidsDir, fmriprep_dir: WIZ.fmriprepDir, space: WIZ.space, ...extra};
}

// ---- build / preview ----------------------------------------------------------------------------
function scheduleBuild() {
    clearTimeout(wiz.timer);
    wiz.timer = setTimeout(build, 300);
}

async function build() {
    const seq = ++wiz.seq;
    try {
        const {status, data} = await postJson('/api/wizard/build', requestBody());
        if (seq !== wiz.seq) return;  // a newer request is in flight
        if (status !== 200) return showError(data.error || `HTTP ${status}`);
        showError('');
        wiz.preview = data.preview;
        renderReview(data.preview, data.preflight);
        renderRecipes();
        renderPairs();
    } catch (e) {
        if (seq === wiz.seq) showError(`Preview failed: ${e.message}`);
    }
}

function renderReview(preview, preflight) {
    const section = (title, items, cls) => {
        const ul = el('ul', {className: 'mb-2 ps-3 ' + (cls || '')}, ...items.map((t) => el('li', {textContent: t})));
        return [el('div', {className: 'fw-bold', textContent: title}), ul];
    };
    const parts = [
        ...section(`Regressors (${preview.regressors.length})`, preview.regressors, 'wiz-regressors'),
        ...section('Nuisance', [preview.nuisance.length ? `${preview.nuisance.length} columns` : 'none']),
        ...section(`Contrasts (${preview.contrasts.length})`, preview.contrasts),
    ];
    // class hooks used by the tests: one .wiz-regressor per regressor, warnings in .wiz-warnings
    parts[1].querySelectorAll('li').forEach((li) => li.classList.add('wiz-regressor'));
    if (preview.warnings.length) {
        const w = section('Warnings', preview.warnings, 'text-warning wiz-warnings');
        parts.push(...w);
    }
    if (preflight) {
        const tone = {blocked: 'danger', warnings: 'warning', ready: 'success'}[preflight.verdict] || 'secondary';
        const verdict = el('div', {className: `alert alert-${tone} py-1 mb-1 preflight-verdict`}, 'Readiness: ',
            el('strong', {textContent: preflight.verdict || 'unknown'}));
        const list = el('ul', {className: 'list-unstyled mb-0'});
        for (const c of preflight.checks || []) {
            const li = el('li', {className: `small ${c.severity === 'error' ? 'text-danger' : 'text-warning'}`,
                textContent: `${c.subject ? 'sub-' + c.subject + ': ' : ''}${c.message}`});
            if (c.fix) li.append(el('div', {className: 'preflight-fix text-muted', textContent: '→ ' + c.fix}));
            list.append(li);
        }
        parts.push(verdict, list);
    }
    $('wiz-review').replaceChildren(...parts);
}

// ---- recipes ------------------------------------------------------------------------------------
function conditionOptions(current) {
    const fromPreview = (wiz.preview?.regressors || []).filter((r) => r.startsWith('trial_type.')).map((r) => r.slice(11));
    const base = (wiz.scan.columns.trial_type || []).filter((c) => !excluded().includes(c));
    return [...new Set([...base, ...fromPreview, ...(current ? [current] : [])])];
}

function paramOptions(kind, recipe, current) {
    const cols = Object.keys(wiz.scan.columns).filter((c) => c !== 'trial_type');
    switch (kind) {
        case 'condition': case 'conditions': return conditionOptions(Array.isArray(current) ? '' : current);
        case 'column': return cols;
        case 'numeric_column': return wiz.scan.numeric;
        case 'regressor': return [...new Set([...(wiz.preview?.regressors || []), ...(current ? [current] : [])])];
        case 'value': case 'values': return wiz.scan.columns[recipe.params.column] || [];
        default: return [];
    }
}

function paramField(recipe, spec) {
    const {name, kind} = spec;
    const set = (v) => { recipe.params[name] = v; scheduleBuild(); };
    const common = {className: 'form-control form-control-sm'};
    let input;
    if (kind === 'bool') {
        input = el('input', {type: 'checkbox', className: 'form-check-input', checked: !!recipe.params[name]});
        input.addEventListener('change', () => set(input.checked));
    } else if (kind === 'int') {
        input = el('input', {...common, type: 'number', min: 1, max: 3, value: recipe.params[name] ?? ''});
        input.addEventListener('change', () => set(input.value === '' ? undefined : Number(input.value)));
    } else if (kind === 'text') {
        input = el('input', {...common, type: 'text', value: recipe.params[name] ?? ''});
        input.addEventListener('change', () => set(input.value.trim()));
    } else {
        const multi = kind === 'conditions' || kind === 'values';
        const opts = paramOptions(kind, recipe, recipe.params[name]);
        input = el('select', {className: 'form-select form-select-sm', multiple: multi}, ...opts.map((o) => option(o)));
        if (multi) {
            for (const o of input.options) o.selected = (recipe.params[name] || []).includes(o.value);
            input.addEventListener('change', () => set([...input.selectedOptions].map((o) => o.value)));
        } else {
            if (!opts.includes(recipe.params[name]) && opts.length && spec.required) recipe.params[name] = opts[0];
            input.value = recipe.params[name] ?? '';
            input.addEventListener('change', () => {
                recipe.params[name] = input.value;
                if (kind === 'column') delete recipe.params.value, delete recipe.params.values;
                scheduleBuild();
                if (kind === 'column') renderRecipes();
            });
        }
    }
    input.dataset.param = name;
    const label = el('label', {className: 'form-label small mb-0', textContent: spec.label + (spec.required ? ' *' : '')});
    return el('div', {className: kind === 'bool' ? 'form-check mb-1' : 'mb-1'}, ...(kind === 'bool' ? [input, label] : [label, input]));
}

function renderRecipes() {
    const nodes = wiz.recipes.map((recipe, i) => {
        const def = wiz.scan.catalog.find((c) => c.id === recipe.id);
        const remove = el('button', {type: 'button', className: 'btn btn-sm btn-outline-danger', title: 'Remove'},
            el('i', {className: 'fas fa-times'}));
        remove.addEventListener('click', () => { wiz.recipes.splice(i, 1); renderRecipes(); scheduleBuild(); });
        return el('div', {className: 'border rounded p-2 mb-2 wiz-recipe'},
            el('div', {className: 'd-flex justify-content-between'}, el('strong', {className: 'small', textContent: def.title}), remove),
            ...def.params.map((spec) => paramField(recipe, spec)));
    });
    $('wiz-recipes').replaceChildren(...nodes);
}

// ---- contrast pairs -----------------------------------------------------------------------------
function multiSelect(selected, onChange) {
    const sel = el('select', {className: 'form-select form-select-sm', multiple: true},
        ...[...new Set([...(wiz.preview?.regressors || []), ...selected])].map((r) => option(r)));
    for (const o of sel.options) o.selected = selected.includes(o.value);
    sel.addEventListener('change', () => onChange([...sel.selectedOptions].map((o) => o.value)));
    return sel;
}

function renderPairs() {
    const rows = wiz.pairs.map((pair, i) => {
        const name = el('input', {className: 'form-control form-control-sm', value: pair.name});
        name.addEventListener('change', () => { pair.name = name.value.trim(); scheduleBuild(); });
        const remove = el('button', {type: 'button', className: 'btn btn-sm btn-outline-danger'}, el('i', {className: 'fas fa-times'}));
        remove.addEventListener('click', () => { wiz.pairs.splice(i, 1); renderPairs(); scheduleBuild(); });
        const cell = (n) => el('td', {}, n);
        return el('tr', {}, cell(name),
            cell(multiSelect(pair.positive, (v) => { pair.positive = v; scheduleBuild(); })),
            cell(multiSelect(pair.negative, (v) => { pair.negative = v; scheduleBuild(); })), cell(remove));
    });
    $('wiz-pair-table').tBodies[0].replaceChildren(...rows);
}

// ---- scan / setup -------------------------------------------------------------------------------
function defaultSavePath() {
    const dir = (WIZ.modelsDir || 'studies').replace(/\/$/, '');
    return `${dir}/${$('wiz-name').value.trim() || 'model'}.json`;
}

async function loadScan(task) {
    const {status, data} = await postJson('/api/wizard/scan', {bids_dir: WIZ.bidsDir, fmriprep_dir: WIZ.fmriprepDir, task});
    if (status !== 200) return showError(data.error || `HTTP ${status}`);
    wiz.scan = data;
    wiz.recipes = [];
    wiz.preview = null;
    $('wiz-task').replaceChildren(...data.tasks.map((t) => option(t)));
    $('wiz-task').value = data.task;
    $('wiz-conditions').replaceChildren(...(data.columns.trial_type || []).map((c) => {
        const input = el('input', {type: 'checkbox', className: 'form-check-input', value: c, checked: true});
        input.addEventListener('change', scheduleBuild);
        return el('label', {className: 'form-check small'}, input, ' ', c);
    }));
    $('wiz-name').value = `${data.task}_model`;
    if (!wiz.pathEdited) $('wiz-save-path').value = defaultSavePath();
    $('wiz-recipe-add').replaceChildren(...data.catalog.map((c) => option(c.id, c.title)));
    $('wiz-recipe-add').dispatchEvent(new Event('change'));
    const current = $('wiz-nuisance').value;
    $('wiz-nuisance').replaceChildren(...Object.keys(data.nuisance_presets).map((n) => option(n)), option('custom', 'custom...'));
    $('wiz-nuisance').value = current || 'none';
    renderRecipes();
    build();
}

async function save(overwrite = false) {
    try {
        const {status, data} = await postJson('/api/wizard/build', requestBody({save_path: $('wiz-save-path').value.trim(), overwrite}));
        if (status === 409 && !overwrite) {
            if (confirm(`File already exists:\n${$('wiz-save-path').value}\n\nOverwrite?`)) return save(true);
            return;
        }
        if (status !== 200) return showError(data.error || `HTTP ${status}`);
        const put = await fetch(`/api/projects/${WIZ.projectId}`, {  // merges into the stored config (the /config endpoint replaces it)
            method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({config: {models_file: data.saved}})});
        if (!put.ok) return showError(`Model saved to ${data.saved} but the project could not be updated (HTTP ${put.status}).`);
        window.location.href = `/analysis/${WIZ.projectId}`;
    } catch (e) {
        showError(`Save failed: ${e.message}`);
    }
}

function init() {
    const nuisance = $('wiz-nuisance');
    $('wiz-task').addEventListener('change', () => loadScan($('wiz-task').value));
    $('wiz-add-recipe').addEventListener('click', () => {
        wiz.recipes.push({id: $('wiz-recipe-add').value, params: {}});
        renderRecipes();
        scheduleBuild();
    });
    $('wiz-recipe-add').addEventListener('change', () => {
        $('wiz-recipe-help').textContent = wiz.scan.catalog.find((c) => c.id === $('wiz-recipe-add').value)?.description || '';
    });
    nuisance.addEventListener('change', () => { $('wiz-nuisance-custom').hidden = nuisance.value !== 'custom'; scheduleBuild(); });
    $('wiz-nuisance-custom').addEventListener('change', scheduleBuild);
    $('wiz-auto-contrasts').addEventListener('change', scheduleBuild);
    $('wiz-add-pair').addEventListener('click', () => { wiz.pairs.push({name: '', positive: [], negative: []}); renderPairs(); });
    $('wiz-name').addEventListener('change', () => { if (!wiz.pathEdited) $('wiz-save-path').value = defaultSavePath(); scheduleBuild(); });
    $('wiz-save-path').addEventListener('input', () => { wiz.pathEdited = true; });
    $('wiz-save').addEventListener('click', () => save());
    loadScan('');
}

init();
