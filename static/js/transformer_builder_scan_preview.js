(function () {
  'use strict';

  function createTransformerBuilderScanPreview(config) {
    const {
      getAvailableColumns,
      setAvailableColumns,
      getColumnValues,
      setColumnValues,
      getCurrentPreviewFile,
      setCurrentPreviewFile,
      setLastScanData,
      getEffectiveSourceScope,
      updateScopeHint,
      getRequestedTaskFilter,
      mergeColumnValueMaps,
      normalizeStringArray,
      setStatus,
      escHtml,
      renderColumnsPool,
      refreshPipelineColumnValues,
      scheduleLiveModelValidation,
      launchContext,
      getTargetLevels,
      loadModelForValidation,
      getSelectedModelPath,
    } = config || {};

    if (
      typeof getAvailableColumns !== 'function' ||
      typeof setAvailableColumns !== 'function' ||
      typeof getColumnValues !== 'function' ||
      typeof setColumnValues !== 'function' ||
      typeof getCurrentPreviewFile !== 'function' ||
      typeof setCurrentPreviewFile !== 'function' ||
      typeof setLastScanData !== 'function' ||
      typeof getEffectiveSourceScope !== 'function' ||
      typeof updateScopeHint !== 'function' ||
      typeof getRequestedTaskFilter !== 'function' ||
      typeof mergeColumnValueMaps !== 'function' ||
      typeof normalizeStringArray !== 'function' ||
      typeof setStatus !== 'function' ||
      typeof escHtml !== 'function' ||
      typeof renderColumnsPool !== 'function' ||
      typeof refreshPipelineColumnValues !== 'function' ||
      typeof scheduleLiveModelValidation !== 'function' ||
      typeof getTargetLevels !== 'function' ||
      typeof loadModelForValidation !== 'function' ||
      typeof getSelectedModelPath !== 'function'
    ) {
      throw new Error('Transformer Builder scan/preview dependencies are incomplete.');
    }

    function setPreviewScopeMode(scope) {
      const isEventsPreview = scope === 'events' || scope === 'combined';
      const rowsLabel = document.querySelector('label[for="preview-row-limit"]');
      const rowsSelect = document.getElementById('preview-row-limit');
      const hideNa = document.getElementById('preview-hide-na-cols');
      const hideNaLabel = hideNa ? hideNa.closest('label') : null;
      const resampleBtn = document.getElementById('btn-resample');

      if (rowsSelect) rowsSelect.disabled = !isEventsPreview;
      if (hideNa) hideNa.disabled = !isEventsPreview;
      if (resampleBtn) resampleBtn.disabled = !isEventsPreview;
      if (rowsLabel) rowsLabel.classList.toggle('text-muted', !isEventsPreview);
      if (hideNaLabel) hideNaLabel.classList.toggle('text-muted', !isEventsPreview);
      if (resampleBtn) {
        resampleBtn.title = isEventsPreview
          ? 'Load a different events file'
          : 'Participants source has no file-level resampling';
      }
    }

    function buildParticipantsColumnResult(participantsInfo) {
      const info = (participantsInfo && typeof participantsInfo === 'object')
        ? participantsInfo
        : {};
      const columns = normalizeStringArray(info.columns);
      const sampleValues = (info.sample_values && typeof info.sample_values === 'object')
        ? info.sample_values
        : {};
      const valuesMap = {};
      columns.forEach(column => {
        valuesMap[column] = normalizeStringArray(sampleValues[column]);
      });
      return {
        columns,
        valuesMap,
        sampleStatus: String(info.sample_status || 'missing-file').trim() || 'missing-file',
      };
    }

    function normalizeLaunchStringArray(value) {
      return normalizeStringArray(value).filter(Boolean);
    }

    async function resolveContextModel() {
      if (launchContext?.modelSnapshot && typeof launchContext.modelSnapshot === 'object' && !Array.isArray(launchContext.modelSnapshot)) {
        return launchContext.modelSnapshot;
      }

      const modelPath = String(getSelectedModelPath() || '').trim();
      if (!modelPath) return null;

      try {
        return await loadModelForValidation(modelPath);
      } catch (_error) {
        return null;
      }
    }

    function getLaunchNode(nodes) {
      const nodeIndex = Number.isInteger(launchContext?.nodeIndex)
        ? launchContext.nodeIndex
        : Number.isInteger(Number(launchContext?.nodeIndex))
          ? Number(launchContext.nodeIndex)
          : -1;
      if (nodeIndex >= 0) return nodes[nodeIndex] || null;

      const nodeName = String(launchContext?.nodeName || '').trim();
      if (!nodeName) return null;
      return nodes.find((node) => String(node?.Name || '').trim() === nodeName) || null;
    }

    function getIncomingContrastNamesForNode(draft, node) {
      const destinationName = String(node?.Name || '').trim();
      if (!destinationName || !draft || typeof draft !== 'object') return [];

      const nodes = Array.isArray(draft.Nodes) ? draft.Nodes : [];
      const getNodeByName = (name) => {
        const normalized = String(name || '').trim();
        if (!normalized) return null;
        return nodes.find((entry) => String(entry?.Name || '').trim() === normalized) || null;
      };
      const getNodeContrastNames = (entry) => {
        if (!entry || typeof entry !== 'object') return [];
        const explicit = Array.isArray(entry.Contrasts)
          ? entry.Contrasts.map((contrast) => String(contrast?.Name || '').trim()).filter(Boolean)
          : [];
        const dummy = normalizeLaunchStringArray(entry?.DummyContrasts?.Contrasts);
        return Array.from(new Set([...explicit, ...dummy]));
      };

      const edges = Array.isArray(draft.Edges) ? draft.Edges : [];
      const incoming = [];
      edges.forEach((edge) => {
        if (String(edge?.Destination || '').trim() !== destinationName) return;
        const sourceNode = getNodeByName(edge?.Source);
        const available = getNodeContrastNames(sourceNode);
        const filterValues = normalizeLaunchStringArray(edge?.Filter?.contrast);
        const selected = filterValues.length
          ? available.filter((name) => filterValues.includes(name))
          : available;
        selected.forEach((name) => incoming.push(name));
      });

      if (!incoming.length) {
        const nodeIndex = Number.isInteger(launchContext?.nodeIndex)
          ? launchContext.nodeIndex
          : Number(launchContext?.nodeIndex);
        if (Number.isInteger(nodeIndex) && nodeIndex > 0) {
          getNodeContrastNames(nodes[nodeIndex - 1]).forEach((name) => incoming.push(name));
        }
      }

      return Array.from(new Set(incoming));
    }

    async function resolveTargetNodesForHigherLevelColumns() {
      const draft = await resolveContextModel();
      const nodes = Array.isArray(draft?.Nodes) ? draft.Nodes : [];
      const launchNode = getLaunchNode(nodes);
      if (launchNode) {
        return { draft, nodes: [launchNode] };
      }

      const targetLevels = new Set(normalizeLaunchStringArray(getTargetLevels()).map((level) => String(level || '').trim().toLowerCase()));
      if (!targetLevels.size) {
        return { draft, nodes: [] };
      }

      return {
        draft,
        nodes: nodes.filter((node) => targetLevels.has(String(node?.Level || '').trim().toLowerCase()))
      };
    }

    async function buildHigherLevelSourceColumns(scanData) {
      const { draft, nodes } = await resolveTargetNodesForHigherLevelColumns();
      const higherLevelNodes = nodes.filter((node) => String(node?.Level || '').trim().toLowerCase() !== 'run');
      if (!higherLevelNodes.length) {
        return { columns: [], valuesMap: {} };
      }

      const entityValues = (scanData && scanData.values && typeof scanData.values === 'object')
        ? scanData.values
        : {};
      const valuesMap = {};

      const allEdges = Array.isArray(draft?.Edges) ? draft.Edges : [];
      // Build lookup from ALL draft nodes so edge source lookups (run-level → subject-level)
      // can find the source node even when nodes[] only contains the launch node.
      const allDraftNodes = Array.isArray(draft?.Nodes) ? draft.Nodes : [];
      const nodesByName = Object.fromEntries(
        allDraftNodes.map((n) => [String(n?.Name || '').trim(), n])
      );

      higherLevelNodes.forEach((node) => {
        const nodeName = String(node?.Name || '').trim();
        const ownTerms = normalizeLaunchStringArray(node.GroupBy)
          .filter((term) => term && term !== 'subject');

        // Also include GroupBy terms from source nodes — these are entity
        // columns (e.g. "run", "session") that bidspm carries forward as
        // metadata when building the higher-level design table.
        const sourceTerms = [];
        allEdges.forEach((edge) => {
          if (String(edge?.Destination || '').trim() !== nodeName) return;
          const src = nodesByName[String(edge?.Source || '').trim()];
          if (!src) return;
          normalizeLaunchStringArray(src.GroupBy)
            .filter((t) => t && t !== 'subject' && !ownTerms.includes(t))
            .forEach((t) => { if (!sourceTerms.includes(t)) sourceTerms.push(t); });
        });

        const metadataTerms = [...ownTerms, ...sourceTerms];

        metadataTerms.forEach((term) => {
          if (term === 'contrast') {
            valuesMap.contrast = Array.from(new Set([
              ...normalizeLaunchStringArray(valuesMap.contrast),
              ...getIncomingContrastNamesForNode(draft, node)
            ]));
            return;
          }

          valuesMap[term] = Array.from(new Set([
            ...normalizeLaunchStringArray(valuesMap[term]),
            ...normalizeLaunchStringArray(entityValues[term])
          ]));
        });
      });

      const columns = Object.keys(valuesMap).filter((name) => name && (name === 'contrast' || valuesMap[name].length > 0));
      return { columns, valuesMap };
    }

    function applyEventsScanResult(data, selectedTask = '') {
      const taskSel = document.getElementById('select-task');
      const eventsFile = document.getElementById('input-events-file').value.trim();

      setAvailableColumns(data.columns || []);
      setColumnValues(data.columns_by_type || {});
      refreshPipelineColumnValues();
      setLastScanData(data);
      setCurrentPreviewFile(eventsFile || data.sample_file || null);
      renderColumnsPool();
      renderEventsPreview(data);

      taskSel.innerHTML = '<option value="">All tasks</option>';
      (data.tasks || []).forEach(task => {
        const option = document.createElement('option');
        option.value = task;
        option.textContent = task;
        taskSel.appendChild(option);
      });
      const effectiveTask = String(data.selected_task || selectedTask || '').trim();
      if (effectiveTask && (data.tasks || []).includes(effectiveTask)) {
        taskSel.value = effectiveTask;
      }

      return effectiveTask;
    }

    function getPreviewMaxRows() {
      const select = document.getElementById('preview-row-limit');
      const parsed = parseInt(select?.value || '200', 10);
      return Number.isNaN(parsed) ? 200 : parsed;
    }

    async function scanEventsColumns(forceNewPreview = false) {
      const bidsDir = document.getElementById('input-bids-dir').value.trim();
      const eventsFile = document.getElementById('input-events-file').value.trim();
      const selectedTask = getRequestedTaskFilter();

      if (!bidsDir && !eventsFile) {
        setStatus('Enter a BIDS directory or select a single events.tsv file.', 'warning');
        return;
      }

      setStatus('Scanning events files…', 'info');
      setPreviewScopeMode('events');

      const payload = {
        preview_max_rows: getPreviewMaxRows(),
      };
      if (bidsDir) payload.bids_dir = bidsDir;
      if (selectedTask) payload.task_filter = selectedTask;
      if (eventsFile) {
        payload.events_file = eventsFile;
        payload.preview_file = eventsFile;
      } else if (!forceNewPreview && getCurrentPreviewFile()) {
        payload.preview_file = getCurrentPreviewFile();
      }

      const response = await fetch('/api/scan_events_columns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (data.error) throw new Error(data.error);

      const effectiveTask = applyEventsScanResult(data, selectedTask);
      const scopeText = effectiveTask
        ? `for task "${effectiveTask}"`
        : `across ${(data.tasks || []).length} task(s)`;
      setStatus(`Found ${getAvailableColumns().length} columns ${scopeText} — ${data.events_files} events file(s).`, 'success');
      scheduleLiveModelValidation();
    }

    async function scanParticipantsColumns() {
      const bidsDir = document.getElementById('input-bids-dir').value.trim();
      if (!bidsDir) {
        setStatus('Set BIDS Folder first to load participants.tsv columns.', 'warning');
        return;
      }

      setStatus('Scanning participants.tsv columns…', 'info');
      setPreviewScopeMode('participants');

      const response = await fetch(`/api/bids_entities?path=${encodeURIComponent(bidsDir)}`);
      const data = await response.json();
      if (!response.ok || data.error) {
        throw new Error(data.error || 'Could not scan BIDS entities.');
      }

      const participantsResult = buildParticipantsColumnResult(data.participants || {});
      const higherLevelColumns = await buildHigherLevelSourceColumns(data);
      setAvailableColumns(Array.from(new Set([...participantsResult.columns, ...higherLevelColumns.columns])));
      setColumnValues(mergeColumnValueMaps(participantsResult.valuesMap, higherLevelColumns.valuesMap));
      refreshPipelineColumnValues();
      setLastScanData(null);
      setCurrentPreviewFile(null);
      renderColumnsPool();
      renderParticipantsPreview(data.participants || {}, bidsDir);

      const taskSel = document.getElementById('select-task');
      taskSel.innerHTML = '<option value="">— not used for participants scope —</option>';

      if (participantsResult.sampleStatus === 'present') {
        const addedCount = higherLevelColumns.columns.length;
        const suffix = addedCount ? ` plus ${addedCount} node metadata/contrast column(s).` : '.';
        setStatus(`Found ${participantsResult.columns.length} participants.tsv column(s)${suffix}`, 'success');
      } else {
        const addedCount = higherLevelColumns.columns.length;
        const suffix = addedCount ? ` Added ${addedCount} node metadata/contrast column(s).` : '';
        setStatus(`participants.tsv status: ${participantsResult.sampleStatus}. Found ${getAvailableColumns().length} usable column(s).${suffix}`, 'warning');
      }
      scheduleLiveModelValidation();
    }

    async function scanCombinedColumns(forceNewPreview = false) {
      const bidsDir = document.getElementById('input-bids-dir').value.trim();
      if (!bidsDir) {
        setStatus('Combined scope requires BIDS Folder for participants.tsv. Falling back to events scope.', 'warning');
        await scanEventsColumns(forceNewPreview);
        return;
      }

      setStatus('Scanning events + participants columns…', 'info');
      setPreviewScopeMode('combined');

      const selectedTask = getRequestedTaskFilter();
      const eventsFile = document.getElementById('input-events-file').value.trim();
      const payload = {
        preview_max_rows: getPreviewMaxRows(),
        bids_dir: bidsDir,
      };
      if (selectedTask) payload.task_filter = selectedTask;
      if (eventsFile) {
        payload.events_file = eventsFile;
        payload.preview_file = eventsFile;
      } else if (!forceNewPreview && getCurrentPreviewFile()) {
        payload.preview_file = getCurrentPreviewFile();
      }

      const [eventsResponse, participantsResponse] = await Promise.all([
        fetch('/api/scan_events_columns', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }),
        fetch(`/api/bids_entities?path=${encodeURIComponent(bidsDir)}`),
      ]);
      const eventsData = await eventsResponse.json();
      const participantsData = await participantsResponse.json();

      if (!eventsResponse.ok || eventsData.error) {
        throw new Error(eventsData.error || 'Could not scan events columns.');
      }
      if (!participantsResponse.ok || participantsData.error) {
        throw new Error(participantsData.error || 'Could not scan participants columns.');
      }

      const effectiveTask = applyEventsScanResult(eventsData, selectedTask);
      const eventColumns = [...getAvailableColumns()];
      const eventValuesMap = { ...getColumnValues() };
      const participantsResult = buildParticipantsColumnResult(participantsData.participants || {});
      const higherLevelColumns = await buildHigherLevelSourceColumns(participantsData);

      setAvailableColumns(Array.from(new Set([...eventColumns, ...participantsResult.columns, ...higherLevelColumns.columns])));
      setColumnValues(mergeColumnValueMaps(eventValuesMap, participantsResult.valuesMap, higherLevelColumns.valuesMap));
      refreshPipelineColumnValues();
      renderColumnsPool();

      const scopeText = effectiveTask
        ? `for task "${effectiveTask}"`
        : `across ${(eventsData.tasks || []).length} task(s)`;
      setStatus(
        `Found ${getAvailableColumns().length} combined columns (${eventColumns.length} events + ${participantsResult.columns.length} participants + ${higherLevelColumns.columns.length} node metadata/contrast) ${scopeText}.`,
        'success'
      );
      scheduleLiveModelValidation();
    }

    async function scanEvents(forceNewPreview = false) {
      const sourceScope = getEffectiveSourceScope();
      updateScopeHint();
      try {
        if (sourceScope === 'participants') {
          await scanParticipantsColumns();
        } else if (sourceScope === 'combined') {
          await scanCombinedColumns(forceNewPreview);
        } else {
          await scanEventsColumns(forceNewPreview);
        }
      } catch (error) {
        setStatus(`Error: ${error.message}`, 'danger');
      }
    }

    function renderEventsPreview(data) {
      const card = document.getElementById('events-preview-card');
      const label = document.getElementById('events-file-label');
      const meta = document.getElementById('events-preview-meta');
      const table = document.getElementById('events-preview-table');
      const body = document.getElementById('events-preview-body');
      const toggle = document.getElementById('events-preview-toggle');
      const hideNaOnlyCols = document.getElementById('preview-hide-na-cols').checked;

      card.style.display = '';
      body.style.display = '';
      toggle.classList.add('open');

      const headers = data.sample_headers || [];
      const rows = data.sample_rows || [];

      if (!headers.length) {
        label.textContent = data.sample_file || 'No preview file found';
        label.title = label.textContent;
        meta.textContent = '';
        table.innerHTML = `
          <thead><tr><th>Preview</th></tr></thead>
          <tbody><tr><td class="na-cell">No readable events preview available for this dataset.</td></tr></tbody>
        `;
        return;
      }

      label.textContent = data.sample_file || '';
      label.title = data.sample_file || '';

      const totalRows = data.sample_total_rows || rows.length;
      const shownRows = rows.length;
      meta.textContent = data.sample_truncated
        ? `showing ${shownRows} / ${totalRows} rows (change Rows to load more)`
        : `${shownRows} rows`;

      let visibleIdx = headers.map((_, index) => index);
      if (hideNaOnlyCols && rows.length) {
        visibleIdx = headers
          .map((_, index) => index)
          .filter(index => rows.some(row => {
            const cell = String(row[index] || '').trim().toLowerCase();
            return cell !== '' && cell !== 'n/a' && cell !== 'nan';
          }));
        if (!visibleIdx.length) {
          visibleIdx = headers.map((_, index) => index);
        }
      }

      const thead = document.createElement('thead');
      thead.innerHTML = '<tr>' + visibleIdx.map(index => `<th>${escHtml(headers[index])}</th>`).join('') + '</tr>';
      const tbody = document.createElement('tbody');

      if (!rows.length) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td class="na-cell" colspan="${visibleIdx.length}">File has headers but no rows.</td>`;
        tbody.appendChild(tr);
      } else {
        rows.forEach(row => {
          const tr = document.createElement('tr');
          tr.innerHTML = visibleIdx.map(index => {
            const cell = row[index];
            const isNa = !cell || cell === 'n/a';
            return `<td class="${isNa ? 'na-cell' : ''}">${escHtml(cell || 'n/a')}</td>`;
          }).join('');
          tbody.appendChild(tr);
        });
      }

      table.innerHTML = '';
      table.appendChild(thead);
      table.appendChild(tbody);
    }

    function renderParticipantsPreview(participantsInfo, bidsDir) {
      const card = document.getElementById('events-preview-card');
      const label = document.getElementById('events-file-label');
      const meta = document.getElementById('events-preview-meta');
      const table = document.getElementById('events-preview-table');
      const body = document.getElementById('events-preview-body');
      const toggle = document.getElementById('events-preview-toggle');

      const info = (participantsInfo && typeof participantsInfo === 'object') ? participantsInfo : {};
      const columns = normalizeStringArray(info.columns);
      const sampleValues = (info.sample_values && typeof info.sample_values === 'object') ? info.sample_values : {};
      const sampleStatus = String(info.sample_status || 'missing-file').trim() || 'missing-file';
      const fileLabel = bidsDir ? `${bidsDir.replace(/\/$/, '')}/participants.tsv` : 'participants.tsv';

      card.style.display = '';
      body.style.display = '';
      toggle.classList.add('open');

      label.textContent = fileLabel;
      label.title = fileLabel;
      meta.textContent = `${columns.length} column(s) • status: ${sampleStatus}`;

      if (!columns.length) {
        table.innerHTML = `
          <thead><tr><th>participants.tsv</th></tr></thead>
          <tbody><tr><td class="na-cell">No participants columns detected. Check participants.tsv in the selected BIDS folder.</td></tr></tbody>
        `;
        return;
      }

      const rows = columns.map(column => {
        const values = normalizeStringArray(sampleValues[column]);
        const renderedValues = values.length ? values.slice(0, 12).join(', ') : 'n/a';
        return `<tr><td>${escHtml(column)}</td><td>${escHtml(renderedValues)}</td></tr>`;
      }).join('');

      table.innerHTML = `
        <thead><tr><th>Column</th><th>Sample values</th></tr></thead>
        <tbody>${rows}</tbody>
      `;
    }

    async function resamplePreview() {
      const button = document.getElementById('btn-resample');
      button.disabled = true;
      button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Loading…';
      try {
        setCurrentPreviewFile(null);
        await scanEvents(true);
      } finally {
        button.disabled = false;
        button.innerHTML = '<i class="fas fa-random me-1"></i>Different file';
      }
    }

    return Object.freeze({
      renderEventsPreview,
      renderParticipantsPreview,
      resamplePreview,
      scanEvents,
    });
  }

  window.BIDSPMTransformerBuilderScanPreview = createTransformerBuilderScanPreview;
})();