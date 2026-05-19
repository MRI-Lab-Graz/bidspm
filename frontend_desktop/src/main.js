import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const DEFAULT_BACKEND_URL = process.env.BIDSPM_BACKEND_URL || 'http://127.0.0.1:5100'
let backendBaseUrl = normalizeBackendUrl(DEFAULT_BACKEND_URL)

function normalizeBackendUrl(url) {
  const trimmed = String(url || '').trim()
  if (!trimmed) {
    throw new Error('Backend URL is required')
  }

  const parsed = new URL(trimmed)
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Backend URL must use http or https')
  }

  const withoutTrailingSlash = parsed.toString().replace(/\/+$/, '')
  return withoutTrailingSlash
}

async function backendRequest(pathname, { method = 'GET', body = null } = {}) {
  const url = `${backendBaseUrl}${pathname}`
  const headers = {
    Accept: 'application/json'
  }

  const requestOptions = {
    method,
    headers
  }

  if (body !== null) {
    headers['Content-Type'] = 'application/json'
    requestOptions.body = JSON.stringify(body)
  }

  const response = await fetch(url, requestOptions)
  const text = await response.text()

  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = { raw: text }
    }
  }

  if (!response.ok) {
    const message = payload?.error || `Request failed (${response.status})`
    throw new Error(message)
  }

  return payload
}

function createMainWindow() {
  const window = new BrowserWindow({
    width: 1260,
    height: 860,
    minWidth: 980,
    minHeight: 680,
    backgroundColor: '#f4f1e7',
    title: 'BIDSPM Desktop',
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  window.loadFile(join(__dirname, 'renderer', 'index.html'))
}

ipcMain.handle('app:getBackendBaseUrl', async () => {
  return backendBaseUrl
})

ipcMain.handle('app:setBackendBaseUrl', async (_event, url) => {
  backendBaseUrl = normalizeBackendUrl(url)
  return backendBaseUrl
})

ipcMain.handle('app:openExternal', async (_event, url) => {
  const target = new URL(url)
  await shell.openExternal(target.toString())
  return true
})

ipcMain.handle('api:listProjects', async () => {
  return backendRequest('/api/projects')
})

ipcMain.handle('api:createProject', async (_event, payload) => {
  return backendRequest('/api/projects', {
    method: 'POST',
    body: payload
  })
})

ipcMain.handle('api:deleteProject', async (_event, projectId) => {
  const id = encodeURIComponent(String(projectId || '').trim())
  if (!id) {
    throw new Error('Project id is required')
  }

  return backendRequest(`/api/projects/${id}`, {
    method: 'DELETE'
  })
})

ipcMain.handle('api:duplicateProject', async (_event, projectId, newName) => {
  const id = encodeURIComponent(String(projectId || '').trim())
  if (!id) {
    throw new Error('Project id is required')
  }

  const body = {}
  if (newName && String(newName).trim()) {
    body.name = String(newName).trim()
  }

  return backendRequest(`/api/projects/${id}/duplicate`, {
    method: 'POST',
    body
  })
})

ipcMain.handle('api:getProjectPreflight', async (_event, projectId) => {
  const id = encodeURIComponent(String(projectId || '').trim())
  if (!id) {
    throw new Error('Project id is required')
  }

  return backendRequest(`/api/projects/${id}/preflight`)
})

app.whenReady().then(() => {
  app.setName('BIDSPM Desktop')
  createMainWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})