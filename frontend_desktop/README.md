# BIDSPM Desktop Frontend (Scaffold)

This folder contains the initial desktop-frontend migration scaffold inspired by the DataLad-desktop architecture.

The structure follows a strict split:

- `src/main.js`: Electron main process and backend adapter boundary
- `src/preload.js`: safe bridge API for renderer
- `src/renderer/*`: HTML/CSS/JS frontend UI

## Current scope

Implemented first vertical slice:

- Backend URL configuration (`http://127.0.0.1:5100` by default)
- Project list (`GET /api/projects`)
- Project creation (`POST /api/projects`)
- Project duplication (`POST /api/projects/<id>/duplicate`)
- Project deletion (`DELETE /api/projects/<id>`)
- Project preflight checks (`GET /api/projects/<id>/preflight`)
- Open existing Flask pages in system browser (`/analysis/<project_id>`, `/model_editor/<project_id>`)

## Run

1. Start BIDSPM Flask backend in the repo root:

```bash
python bidspm_gui.py
```

2. In another terminal:

```bash
cd frontend_desktop
npm install
npm start
```

## Running On Remote Headless Servers

If you are connected to a remote Ubuntu server (for example from macOS) and see:

```text
Missing X server or $DISPLAY
```

that means Electron has no GUI display and cannot open an interactive window on that host.

Use one of these approaches:

1) Preferred: run desktop artifacts locally on your machine (macOS/Windows/Linux).
2) Remote smoke run only:

```bash
npm run start:xvfb
```

3) Remote interactive GUI: use X forwarding (for example `ssh -Y`) with a local X server.

Optional custom backend URL:

```bash
BIDSPM_BACKEND_URL=http://127.0.0.1:5100 npm start
```

## Notes

This is intentionally incremental. The analysis/model/transformer screens are still served by the Flask app and opened externally for now.

## Packaging and Release Targets

This frontend is configured for desktop packaging on:

- Linux (`AppImage`, `deb`, `tar.gz`)
- macOS (`dmg`, `zip`)
- Windows (`nsis`, `zip`)

Local build commands:

```bash
npm run dist:linux
npm run dist:mac
npm run dist:win
```

General package build (current host platform):

```bash
npm run dist
```

Output artifacts are generated in:

```text
frontend_desktop/dist/
```

Unsigned builds are produced by default. Code-signing and notarization can be layered in later.

## One-Command CI Release (Linux + macOS + Windows)

Use GitHub Actions workflow [desktop-builds.yml](../.github/workflows/desktop-builds.yml) to build all platforms and optionally publish a GitHub Release.

Build artifacts only:

```bash
gh workflow run desktop-builds.yml
```

Build plus publish release assets in one command:

```bash
gh workflow run desktop-builds.yml \
	-f publish_release=true \
	-f release_tag=v0.1.0 \
	-f release_name="BIDSPM Desktop v0.1.0" \
	-f prerelease=true
```

Track progress:

```bash
gh run list --workflow desktop-builds.yml
gh run watch
```