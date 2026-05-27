(function(global) {
  function createLaunchHelpers(options = {}) {
    const transformerLaunchContextKey = String(
      options.transformerLaunchContextKey || 'bidspm.transformerLaunchContext'
    );
    const pendingTransformerKey = String(
      options.pendingTransformerKey || 'bidspm.pendingTransformerModel'
    );

    function normalizeLaunchStringArray(value) {
      if (Array.isArray(value)) {
        return value.map(item => String(item || '').trim()).filter(Boolean);
      }
      if (value === undefined || value === null || typeof value === 'object') return [];
      const normalized = String(value || '').trim();
      return normalized ? [normalized] : [];
    }

    function readTransformerLaunchContext() {
      try {
        const raw = sessionStorage.getItem(transformerLaunchContextKey);
        if (!raw) return null;
        return JSON.parse(raw);
      } catch (error) {
        return null;
      }
    }

    function clearTransformerLaunchContext() {
      try {
        sessionStorage.removeItem(transformerLaunchContextKey);
      } catch (error) {
        // Ignore storage cleanup failures.
      }
    }

    function createTransformerLaunchId() {
      return `transformer-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    }

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
      } catch (error) {
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

    function readPendingTransformerPayload() {
      try {
        const raw = sessionStorage.getItem(pendingTransformerKey);
        if (!raw) return null;
        return JSON.parse(raw);
      } catch (error) {
        return null;
      }
    }

    function clearPendingTransformerPayload() {
      try {
        sessionStorage.removeItem(pendingTransformerKey);
      } catch (error) {
        // Ignore storage cleanup failures.
      }
    }

    return {
      normalizeLaunchStringArray,
      readTransformerLaunchContext,
      clearTransformerLaunchContext,
      createTransformerLaunchId,
      normalizeFsPath,
      stripPathQueryAndHash,
      safeDecodePath,
      areModelPathsEquivalent,
      readPendingTransformerPayload,
      clearPendingTransformerPayload,
    };
  }

  global.BidspmModelEditorLaunch = {
    createLaunchHelpers,
  };
})(window);