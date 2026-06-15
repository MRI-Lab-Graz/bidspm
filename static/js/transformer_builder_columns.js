(function () {
  'use strict';

  function createTransformerBuilderColumns(config) {
    const {
      getAvailableColumns,
      getColumnValues,
      getPipelineColumnValues,
      setPipelineColumnValues,
      extractOpsFromCard,
      escHtml,
      escAttr,
    } = config || {};

    if (
      typeof getAvailableColumns !== 'function' ||
      typeof getColumnValues !== 'function' ||
      typeof getPipelineColumnValues !== 'function' ||
      typeof setPipelineColumnValues !== 'function' ||
      typeof extractOpsFromCard !== 'function' ||
      typeof escHtml !== 'function' ||
      typeof escAttr !== 'function'
    ) {
      throw new Error('Transformer Builder columns dependencies are incomplete.');
    }

    function renderColumnsPool() {
      const sourcePool = document.getElementById('columns-pool');
      const generatedPool = document.getElementById('generated-columns-pool');
      const sourceColumns = getAvailableColumns().map(col => ({ name: col, generated: false, sourceKind: 'source' }));
      const generatedColumns = getGeneratedColumns();

      document.getElementById('source-columns-count').textContent = sourceColumns.length ? `${sourceColumns.length}` : '';
      document.getElementById('generated-columns-count').textContent = generatedColumns.length ? `${generatedColumns.length}` : '';

      renderColumnList(sourcePool, sourceColumns, {
        emptyHtml: '<div class="text-muted small text-center py-4"><i class="fas fa-search d-block mb-2" style="font-size:1.8rem; opacity:.25;"></i>Scan a BIDS folder<br>to see columns</div>'
      });
      renderColumnList(generatedPool, generatedColumns, {
        emptyHtml: '<div class="columns-empty-note">Generated outputs from the pipeline will appear here.</div>'
      });
    }

    function renderColumnList(container, columnInfos, options = {}) {
      if (!columnInfos.length) {
        container.innerHTML = options.emptyHtml || '<div class="text-muted small text-center">No columns found.</div>';
        return;
      }

      container.innerHTML = columnInfos.map(colInfo => {
        const col = colInfo.name;
        const vals = getColumnDomain(col);
        const shown = vals.slice(0, 8);
        const extra = vals.length - shown.length;
        const valHtml = shown.length ? `
          <div class="col-vals">
            ${shown.map(v => `<span class="col-val-tag">${escHtml(v)}</span>`).join('')}
            ${extra > 0 ? `<span class="col-val-more">+${extra} more</span>` : ''}
          </div>` : '';
        return `
          <div class="col-badge ${colInfo.generated ? 'generated' : ''}" draggable="true" data-col="${escAttr(col)}">
            <i class="fas fa-columns"></i>
            <span>${escHtml(col)}</span>
            ${colInfo.generated ? '<span class="col-badge-note">generated</span>' : ''}
          </div>
          ${valHtml}`;
      }).join('');

      container.querySelectorAll('.col-badge').forEach(badge => {
        badge.addEventListener('dragstart', e => {
          e.dataTransfer.setData('text/plain', badge.dataset.col);
          e.dataTransfer.effectAllowed = 'copy';
          badge.classList.add('dragging');
          document.querySelectorAll('.col-drop-zone').forEach(zone => zone.classList.add('ready'));
        });
        badge.addEventListener('dragend', () => {
          badge.classList.remove('dragging');
          document.querySelectorAll('.col-drop-zone').forEach(zone => zone.classList.remove('ready', 'drag-over'));
        });
      });
    }

    function getSelectableColumns() {
      const seen = new Set();
      const combined = [];

      getAvailableColumns().forEach(col => {
        const normalized = String(col || '').trim();
        if (!normalized || seen.has(normalized)) return;
        seen.add(normalized);
        combined.push({ name: normalized, generated: false });
      });

      getGeneratedColumns().forEach(col => {
        const normalized = String(col?.name || '').trim();
        if (!normalized || seen.has(normalized)) return;
        seen.add(normalized);
        combined.push({ name: normalized, generated: true });
      });

      return combined;
    }

    let seededGeneratedColumns = [];

    function setSeedColumns(columns) {
      seededGeneratedColumns = Array.isArray(columns) ? columns : [];
    }

    function getGeneratedColumns() {
      const generated = [];
      const seen = new Set();

      document.querySelectorAll('#op-pipeline .op-card').forEach(card => {
        const opType = card.dataset.opType;
        const inferred = inferGeneratedColumnsForCard(card, opType);
        inferred.forEach(colInfo => {
          const normalized = String(colInfo?.name || '').trim();
          if (!normalized || seen.has(normalized)) return;
          seen.add(normalized);
          generated.push({
            name: normalized,
            generated: true,
            sourceKind: colInfo.sourceKind || 'generated',
            derivedFrom: colInfo.derivedFrom || opType
          });
        });
      });

      seededGeneratedColumns.forEach(colInfo => {
        const normalized = String(colInfo?.name || '').trim();
        if (!normalized || seen.has(normalized)) return;
        seen.add(normalized);
        generated.push({ name: normalized, generated: true, sourceKind: 'model-existing', derivedFrom: 'loaded model' });
      });

      return generated;
    }

    function getGeneratedModelXRegressorSuggestions() {
      const suggestions = [];
      const seen = new Set();

      const addSuggestion = (value) => {
        const normalized = String(value || '').trim();
        if (!normalized || seen.has(normalized)) return;
        seen.add(normalized);
        suggestions.push(normalized);
      };

      getGeneratedColumns().forEach(colInfo => {
        const columnName = String(colInfo?.name || '').trim();
        if (!columnName) return;

        addSuggestion(columnName);

        if (['Concatenate', 'Filter'].includes(String(colInfo?.derivedFrom || '').trim())) {
          getColumnDomain(columnName).forEach(level => {
            const normalizedLevel = String(level || '').trim();
            if (!normalizedLevel || normalizedLevel === 'n/a') return;
            addSuggestion(`${columnName}.${normalizedLevel}`);
          });
        }
      });

      return suggestions;
    }

    function inferGeneratedColumnsForCard(card, opType) {
      if (opType === 'Factor') {
        return inferFactorGeneratedColumns(card);
      }

      const generated = [];
      card.querySelectorAll('input[data-field="Output"]').forEach(input => {
        const raw = input.value.trim();
        if (!raw) return;
        raw.split(',').map(v => v.trim()).filter(Boolean).forEach(name => {
          generated.push({ name, sourceKind: 'explicit-output', derivedFrom: opType });
        });
      });
      return generated;
    }

    function inferFactorGeneratedColumns(card) {
      const inputZone = card.querySelector('.col-drop-zone[data-field="Input"]');
      if (!inputZone) return [];

      const inputColumns = getZoneValue(inputZone);
      if (!inputColumns.length) return [];

      const levelSets = inputColumns.map(col => {
        const values = getColumnDomain(col).map(v => String(v || '').trim()).filter(Boolean);
        return [...new Set(values)].sort((a, b) => a.localeCompare(b));
      });

      if (levelSets.some(levels => !levels.length)) return [];

      const combinations = buildFactorCombinations(inputColumns, levelSets, 0, [], []);
      return combinations.map(name => ({
        name,
        sourceKind: 'factor-derived',
        derivedFrom: `Factor(${inputColumns.join(', ')})`
      }));
    }

    function buildFactorCombinations(columns, levelSets, index, parts, names) {
      if (index >= columns.length) {
        if (parts.length) names.push(parts.join('_'));
        return names;
      }

      const col = columns[index];
      levelSets[index].forEach(level => {
        buildFactorCombinations(columns, levelSets, index + 1, [...parts, col, level], names);
      });
      return names;
    }

    function getZoneValue(zone) {
      return Array.from(zone.querySelectorAll('.col-chip')).map(chip => chip.dataset.col);
    }

    function getColumnDomain(name) {
      return getPipelineColumnValues()[name] || getColumnValues()[name] || [];
    }

    function refreshPipelineColumnValues() {
      const valuesMap = buildPipelineColumnValues();
      setPipelineColumnValues(valuesMap);
      return valuesMap;
    }

    function buildPipelineColumnValues() {
      const valuesMap = {};

      Object.entries(getColumnValues() || {}).forEach(([name, values]) => {
        valuesMap[name] = normalizeValueList(values);
      });

      document.querySelectorAll('#op-pipeline .op-card').forEach(card => {
        const ops = extractOpsFromCard(card);
        ops.forEach(op => applyOperationValueDomains(valuesMap, op));
      });

      return valuesMap;
    }

    function applyOperationValueDomains(valuesMap, op) {
      const opName = String(op?.Name || '').trim();
      if (!opName) return;

      const inputColumns = normalizeColumnList(op.Input);
      const outputColumns = normalizeColumnList(op.Output);
      const inputColumn = inputColumns[0] || '';
      const targetColumn = outputColumns[0] || inputColumn;

      switch (opName) {
        case 'Filter': {
          if (!targetColumn) return;
          const inputValues = getDomainFromMap(valuesMap, inputColumn);
          valuesMap[targetColumn] = inferFilterDomain(op.Query, inputColumn, inputValues);
          return;
        }
        case 'Concatenate': {
          const outputName = outputColumns[0];
          if (!outputName || !inputColumns.length) return;
          const levelSets = inputColumns.map(col => getDomainFromMap(valuesMap, col));
          if (levelSets.some(levels => !levels.length)) return;
          valuesMap[outputName] = normalizeValueList(buildDomainCombinations(levelSets));
          return;
        }
        case 'Factor': {
          if (!inputColumns.length) return;
          const levelSets = inputColumns.map(col => getDomainFromMap(valuesMap, col));
          if (levelSets.some(levels => !levels.length)) return;
          const factorColumns = buildFactorCombinations(inputColumns, levelSets, 0, [], []);
          factorColumns.forEach(name => {
            valuesMap[name] = ['0', '1'];
          });
          return;
        }
        case 'Replace': {
          if (!targetColumn) return;
          const inputValues = getDomainFromMap(valuesMap, inputColumn);
          const replacements = Array.isArray(op.Replace) ? op.Replace : [];
          valuesMap[targetColumn] = normalizeValueList(inputValues.map(value => applyReplacementRules(value, replacements)));
          return;
        }
        case 'Copy': {
          if (!inputColumns.length || !outputColumns.length) return;
          outputColumns.forEach((outputName, index) => {
            const sourceName = inputColumns[index] || inputColumns[inputColumns.length - 1];
            if (!outputName || !sourceName) return;
            valuesMap[outputName] = [...getDomainFromMap(valuesMap, sourceName)];
          });
          return;
        }
        case 'Assign': {
          const targetColumns = normalizeColumnList(op.Target);
          if (!inputColumns.length || !targetColumns.length) return;
          const assigned = targetColumns.map((targetName, index) => {
            const sourceName = inputColumns[index] || inputColumns[inputColumns.length - 1];
            return { targetName, sourceName };
          });

          if (outputColumns.length) {
            assigned.forEach(({ sourceName }, index) => {
              const outputName = outputColumns[index] || outputColumns[outputColumns.length - 1];
              if (!outputName || !sourceName) return;
              valuesMap[outputName] = [...getDomainFromMap(valuesMap, sourceName)];
            });
            return;
          }

          assigned.forEach(({ targetName, sourceName }) => {
            if (!targetName || !sourceName) return;
            valuesMap[targetName] = [...getDomainFromMap(valuesMap, sourceName)];
          });
          return;
        }
        case 'DropNA': {
          if (!targetColumn) return;
          valuesMap[targetColumn] = [...getDomainFromMap(valuesMap, inputColumn)];
          return;
        }
        case 'Split': {
          if (!inputColumns.length || !outputColumns.length) return;
          outputColumns.forEach(outputName => {
            if (!outputName) return;
            valuesMap[outputName] = [...getDomainFromMap(valuesMap, inputColumn)];
          });
          return;
        }
        case 'LabelIdenticalRows': {
          if (!inputColumns.length) return;
          if (outputColumns.length) {
            outputColumns.forEach(outputName => {
              if (!outputName) return;
              valuesMap[outputName] = [];
            });
            return;
          }
          inputColumns.forEach(col => {
            valuesMap[`${col}_label`] = [];
          });
          return;
        }
        case 'MergeIdenticalRows': {
          return;
        }
        case 'Constant': {
          const outputName = outputColumns[0];
          if (!outputName) return;
          const rawValue = op.Value;
          const constantValue = rawValue === undefined || rawValue === null || rawValue === ''
            ? '1'
            : String(rawValue);
          valuesMap[outputName] = [constantValue];
          return;
        }
        case 'Product':
        case 'Std':
        case 'Sum':
        case 'Scale':
        case 'Mean': {
          if (!targetColumn) return;
          valuesMap[targetColumn] = [...getDomainFromMap(valuesMap, inputColumn)];
          return;
        }
        case 'Threshold': {
          if (!targetColumn) return;
          valuesMap[targetColumn] = op.Binarize
            ? ['0', '1']
            : [...getDomainFromMap(valuesMap, inputColumn)];
          return;
        }
        case 'Select': {
          if (!inputColumns.length) return;
          const keep = new Set(inputColumns);
          Object.keys(valuesMap).forEach(name => {
            if (!keep.has(name)) delete valuesMap[name];
          });
          return;
        }
        case 'Delete': {
          inputColumns.forEach(name => {
            delete valuesMap[name];
          });
          return;
        }
        default:
          return;
      }
    }

    function normalizeColumnList(value) {
      const items = Array.isArray(value) ? value : (value ? [value] : []);
      return items.map(item => String(item || '').trim()).filter(Boolean);
    }

    function normalizeValueList(values) {
      return Array.from(new Set((Array.isArray(values) ? values : [])
        .map(value => String(value ?? '').trim())
        .filter(Boolean)));
    }

    function getDomainFromMap(valuesMap, name) {
      return normalizeValueList(valuesMap[name] || []);
    }

    function buildDomainCombinations(levelSets, index = 0, parts = [], names = []) {
      if (index >= levelSets.length) {
        if (parts.length) names.push(parts.join('_'));
        return names;
      }

      levelSets[index].forEach(level => {
        buildDomainCombinations(levelSets, index + 1, [...parts, level], names);
      });
      return names;
    }

    function inferFilterDomain(query, inputColumn, inputValues) {
      const normalizedInput = String(inputColumn || '').trim();
      const domain = normalizeValueList(inputValues);
      const normalizedQuery = String(query || '').trim();
      if (!normalizedInput || !normalizedQuery || !domain.length) return domain;

      const matched = new Set();
      let sawInputEquality = false;

      normalizedQuery.split('|').map(part => part.trim()).filter(Boolean).forEach(part => {
        const clause = part.replace(/^\(+|\)+$/g, '').trim();
        const match = clause.match(/^(.+?)\s*==\s*(.+)$/);
        if (!match) return;

        const left = String(match[1] || '').trim();
        if (left !== normalizedInput) return;

        sawInputEquality = true;
        const literal = normalizeQueryLiteral(match[2]);
        if (literal) matched.add(literal);
      });

      if (!sawInputEquality) return domain;
      const filtered = domain.filter(value => matched.has(String(value)));
      return filtered.length ? filtered : Array.from(matched);
    }

    function normalizeQueryLiteral(value) {
      const literal = String(value || '').trim();
      if (!literal) return '';
      if ((literal.startsWith('\'') && literal.endsWith('\'')) || (literal.startsWith('"') && literal.endsWith('"'))) {
        return literal.slice(1, -1).trim();
      }
      return literal.replace(/^\(+|\)+$/g, '').trim();
    }

    function applyReplacementRules(value, replacements) {
      let nextValue = String(value ?? '').trim();
      replacements.forEach(rule => {
        const key = String(rule?.key || '').trim();
        if (!key) return;

        const replacement = String(rule?.value ?? '').trim();
        if (nextValue === key) {
          nextValue = replacement;
          return;
        }

        try {
          const regex = new RegExp(key);
          if (regex.test(nextValue)) nextValue = nextValue.replace(regex, replacement);
        } catch (error) {
          // Ignore invalid regex patterns while keeping literal replacements working.
        }
      });
      return nextValue;
    }

    return Object.freeze({
      getSelectableColumns,
      getGeneratedColumns,
      getGeneratedModelXRegressorSuggestions,
      getColumnDomain,
      normalizeColumnList,
      refreshPipelineColumnValues,
      renderColumnsPool,
      setSeedColumns,
    });
  }

  window.BIDSPMTransformerBuilderColumns = createTransformerBuilderColumns;
})();