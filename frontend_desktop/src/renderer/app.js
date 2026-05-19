const api = window.bidspmDesktop

const state = {
  backendBaseUrl: '',
  projects: []
}

const elements = {
  backendUrlDisplay: document.getElementById('backend-url-display'),
  connectionState: document.getElementById('connection-state'),
  backendUrlInput: document.getElementById('backend-url'),
  setBackendUrlButton: document.getElementById('set-backend-url'),
  checkConnectionButton: document.getElementById('check-connection'),
  createProjectForm: document.getElementById('create-project-form'),
  projectNameInput: document.getElementById('project-name'),
  projectDescriptionInput: document.getElementById('project-description'),
  refreshProjectsButton: document.getElementById('refresh-projects'),
  projectsOutput: document.getElementById('projects-output'),
  detailsOutput: document.getElementById('details-output')
}

function setConnectionState(text, tone) {
  elements.connectionState.textContent = text
  elements.connectionState.className = `state-pill state-${tone}`
}

function renderDetails(payload) {
  const text = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2)
  elements.detailsOutput.textContent = text
}

function formatTimestamp(value) {
  if (!value) {
    return 'n/a'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value)
  }

  return date.toLocaleString()
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function renderProjects(projects) {
  if (!projects.length) {
    elements.projectsOutput.innerHTML = '<p class="hint">No projects yet. Create one to begin.</p>'
    return
  }

  const html = projects
    .map((project) => {
      const description = project.description || 'No description'
      return (
        '<article class="project-card">' +
        '<div class="project-head">' +
        '<div>' +
        `<h3 class="project-title">${escapeHtml(project.name)}</h3>` +
        `<p class="project-description">${escapeHtml(description)}</p>` +
        '<p class="project-meta">' +
        `<span>id: ${escapeHtml(project.id)}</span>` +
        `<span>created: ${escapeHtml(formatTimestamp(project.created))}</span>` +
        `<span>last modified: ${escapeHtml(formatTimestamp(project.last_modified))}</span>` +
        '</p>' +
        '</div>' +
        '</div>' +
        '<div class="project-actions">' +
        `<button class="button button-primary button-mini" data-action="open-analysis" data-project-id="${escapeHtml(project.id)}">Analysis</button>` +
        `<button class="button button-ghost button-mini" data-action="open-model" data-project-id="${escapeHtml(project.id)}">Model Editor</button>` +
        `<button class="button button-ghost button-mini" data-action="preflight" data-project-id="${escapeHtml(project.id)}">Preflight</button>` +
        `<button class="button button-ghost button-mini" data-action="duplicate" data-project-id="${escapeHtml(project.id)}">Duplicate</button>` +
        `<button class="button button-danger button-mini" data-action="delete" data-project-id="${escapeHtml(project.id)}">Delete</button>` +
        '</div>' +
        '</article>'
      )
    })
    .join('')

  elements.projectsOutput.innerHTML = html
}

async function loadProjects() {
  try {
    const payload = await api.listProjects()
    state.projects = payload?.projects || []
    elements.backendUrlDisplay.textContent = state.backendBaseUrl
    setConnectionState('Connected', 'success')
    renderProjects(state.projects)
    renderDetails({
      action: 'listProjects',
      count: state.projects.length
    })
  } catch (error) {
    setConnectionState('Connection Error', 'error')
    elements.projectsOutput.innerHTML =
      '<p class="hint">Could not load projects. Check backend URL and running server.</p>'
    renderDetails({
      action: 'listProjects',
      error: String(error.message || error)
    })
  }
}

function routeUrl(pathname) {
  const trimmed = state.backendBaseUrl.replace(/\/+$/, '')
  return `${trimmed}${pathname}`
}

async function onSetBackendUrl() {
  const nextValue = elements.backendUrlInput.value.trim()
  try {
    state.backendBaseUrl = await api.setBackendBaseUrl(nextValue)
    elements.backendUrlInput.value = state.backendBaseUrl
    await loadProjects()
  } catch (error) {
    setConnectionState('Invalid URL', 'warning')
    renderDetails({ action: 'setBackendUrl', error: String(error.message || error) })
  }
}

async function onCreateProject(event) {
  event.preventDefault()

  const name = elements.projectNameInput.value.trim()
  const description = elements.projectDescriptionInput.value.trim()
  if (!name) {
    renderDetails({ action: 'createProject', error: 'Project name is required' })
    return
  }

  try {
    const payload = await api.createProject({ name, description })
    elements.createProjectForm.reset()
    renderDetails(payload)
    await loadProjects()
  } catch (error) {
    renderDetails({ action: 'createProject', error: String(error.message || error) })
  }
}

async function onProjectAction(event) {
  const button = event.target.closest('[data-action]')
  if (!button) {
    return
  }

  const action = button.getAttribute('data-action')
  const projectId = button.getAttribute('data-project-id')
  if (!action || !projectId) {
    return
  }

  if (action === 'open-analysis') {
    await api.openExternal(routeUrl(`/analysis/${encodeURIComponent(projectId)}`))
    return
  }

  if (action === 'open-model') {
    await api.openExternal(routeUrl(`/model_editor/${encodeURIComponent(projectId)}`))
    return
  }

  if (action === 'preflight') {
    try {
      const payload = await api.getProjectPreflight(projectId)
      renderDetails(payload)
    } catch (error) {
      renderDetails({ action: 'preflight', error: String(error.message || error) })
    }
    return
  }

  if (action === 'duplicate') {
    const suggested = state.projects.find((item) => item.id === projectId)?.name || 'copy'
    const newName = window.prompt('Name for duplicated project', `${suggested} Copy`)
    if (newName === null) {
      return
    }

    try {
      const payload = await api.duplicateProject(projectId, newName)
      renderDetails(payload)
      await loadProjects()
    } catch (error) {
      renderDetails({ action: 'duplicate', error: String(error.message || error) })
    }
    return
  }

  if (action === 'delete') {
    const ok = window.confirm('Delete this project permanently?')
    if (!ok) {
      return
    }

    try {
      const payload = await api.deleteProject(projectId)
      renderDetails(payload)
      await loadProjects()
    } catch (error) {
      renderDetails({ action: 'delete', error: String(error.message || error) })
    }
  }
}

async function init() {
  state.backendBaseUrl = await api.getBackendBaseUrl()
  elements.backendUrlInput.value = state.backendBaseUrl
  elements.backendUrlDisplay.textContent = state.backendBaseUrl

  elements.setBackendUrlButton.addEventListener('click', onSetBackendUrl)
  elements.checkConnectionButton.addEventListener('click', loadProjects)
  elements.createProjectForm.addEventListener('submit', onCreateProject)
  elements.refreshProjectsButton.addEventListener('click', loadProjects)
  elements.projectsOutput.addEventListener('click', onProjectAction)

  await loadProjects()
}

void init()