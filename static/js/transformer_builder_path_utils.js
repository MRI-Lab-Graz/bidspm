(function () {
  'use strict';

  function normalizeFsPath(path) {
    const raw = String(path || '').trim().replace(/^['"]+|['"]+$/g, '');
    if (!raw) return '';
    const unified = raw.replace(/\\/g, '/').replace(/\/+/g, '/');
    const absolute = unified.startsWith('/');
    const parts = [];

    unified.split('/').forEach(part => {
      if (!part || part === '.') return;
      if (part === '..') {
        if (parts.length && parts[parts.length - 1] !== '..') {
          parts.pop();
        } else if (!absolute) {
          parts.push(part);
        }
        return;
      }
      parts.push(part);
    });

    const normalized = parts.join('/');
    return absolute ? `/${normalized}` : normalized;
  }

  function stripPathQueryAndHash(path) {
    const normalized = normalizeFsPath(path);
    if (!normalized) return '';

    const hashIdx = normalized.indexOf('#');
    const noHash = hashIdx >= 0 ? normalized.slice(0, hashIdx) : normalized;
    const queryIdx = noHash.indexOf('?');
    return queryIdx >= 0 ? noHash.slice(0, queryIdx) : noHash;
  }

  function safeDecodePath(path) {
    try {
      return decodeURIComponent(path);
    } catch (_error) {
      return path;
    }
  }

  function areModelPathsEquivalent(pathA, pathB) {
    const leftRaw = stripPathQueryAndHash(pathA);
    const rightRaw = stripPathQueryAndHash(pathB);
    if (!leftRaw || !rightRaw) return false;

    const left = normalizeFsPath(safeDecodePath(leftRaw));
    const right = normalizeFsPath(safeDecodePath(rightRaw));
    if (!left || !right) return false;
    if (left === right) return true;

    const leftAbs = left.startsWith('/');
    const rightAbs = right.startsWith('/');
    if (!leftAbs && rightAbs && right.endsWith(`/${left}`)) return true;
    if (!rightAbs && leftAbs && left.endsWith(`/${right}`)) return true;

    return false;
  }

  function getParentPath(path) {
    const normalized = normalizeFsPath(path);
    if (!normalized) return '';
    const idx = normalized.lastIndexOf('/');
    if (idx <= 0) return '/';
    return normalized.slice(0, idx);
  }

  function getFileName(path) {
    const normalized = normalizeFsPath(path);
    if (!normalized) return '';
    const idx = normalized.lastIndexOf('/');
    return idx >= 0 ? normalized.slice(idx + 1) : normalized;
  }

  function normalizeStringArray(value) {
    if (Array.isArray(value)) {
      return value.map(item => String(item || '').trim()).filter(Boolean);
    }
    if (typeof value === 'string') {
      return value.split(',').map(item => item.trim()).filter(Boolean);
    }
    return [];
  }

  window.BIDSPMTransformerBuilderPathUtils = Object.freeze({
    normalizeFsPath,
    stripPathQueryAndHash,
    safeDecodePath,
    areModelPathsEquivalent,
    getParentPath,
    getFileName,
    normalizeStringArray,
  });
})();