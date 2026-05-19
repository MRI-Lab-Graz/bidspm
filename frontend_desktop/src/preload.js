import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('bidspmDesktop', {
  getBackendBaseUrl: () => ipcRenderer.invoke('app:getBackendBaseUrl'),
  setBackendBaseUrl: (url) => ipcRenderer.invoke('app:setBackendBaseUrl', url),
  openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
  listProjects: () => ipcRenderer.invoke('api:listProjects'),
  createProject: (payload) => ipcRenderer.invoke('api:createProject', payload),
  deleteProject: (projectId) => ipcRenderer.invoke('api:deleteProject', projectId),
  duplicateProject: (projectId, newName) => ipcRenderer.invoke('api:duplicateProject', projectId, newName),
  getProjectPreflight: (projectId) => ipcRenderer.invoke('api:getProjectPreflight', projectId)
})