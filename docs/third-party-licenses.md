# Third-party licences of the spm-bids-runner image

Inventory of everything that ends up in the image built from `containers/dockerfile/dockerfile`, made on
2026-10-19 by inspecting the previous build (local tag `spm26-atlas` of the SPM 26 image) file by file, not from memory.
Rule (decided by the user): the image contains **only clearly free/open-source components**. Anything
restrictive (non-commercial, academic-only, EULA, data use terms) or with an unclear or missing licence is
removed at build time, and the build fails if one comes back (`find` guard in the Dockerfile,
`tests/test_image_licences.py`).

Classes: **FREE** (licence named, evidence given), **RESTRICTIVE**, **UNCLEAR/NONE**.
"In image" = in the new image. The MATLAB-Runtime `spm-standalone` image is not part of this and is not
published; users supply it themselves.

## Base system and runtimes

| Component | Version | Licence | Evidence | In image | Action |
|---|---|---|---|---|---|
| Debian trixie base (`python:3.12-slim-trixie`) + 813 apt packages (Octave, nodejs, npm, build-essential, git, vim, BLAS/LAPACK/OpenBLAS ...) | trixie | FREE (DFSG; each package's own licence) | `/etc/apt/sources.list.d/debian.sources`: `Components: main` only; `dpkg-query` lists 0 packages in a `contrib`/`non-free` section; per package `/usr/share/doc/<pkg>/copyright` | yes | keep |
| CPython | 3.12 | FREE, PSF-2.0 | python image | yes | keep |
| GNU Octave | 9.4.0-1 (Debian) | FREE, GPL-3.0-or-later | `/usr/share/doc/octave/copyright` | yes | keep; copied to `licenses/octave-debian-copyright.txt` |
| Octave Forge: io, image, signal, statistics, struct, parallel, control, symbolic | Debian trixie | FREE, GPL-3.0-or-later (symbolic pulls python3-sympy, BSD) | Debian main, `/usr/share/doc/octave-*/copyright` | yes | keep |
| uv | latest at build | FREE, MIT OR Apache-2.0 | astral-sh/uv | yes | keep |
| Python packages (numpy, scipy, matplotlib, pandas, nibabel, nilearn, pybids, bids-validator, jsonschema, pydantic, scikit-learn, requests, certifi, num2words, frozendict, bsmschema, bidspm CLI ...) | as resolved at build | FREE: MIT, BSD-2/3-Clause, Apache-2.0, PSF-2.0, MPL-2.0 (certifi), LGPL (num2words, frozendict), HPND/MIT-CMU (pillow), matplotlib licence (PSF-style), GPL-3.0 (bidspm) | `importlib.metadata` License / License-Expression of every installed distribution | yes | keep |
| npm `bids-validator` + dependencies | 1.14.10 | FREE: MIT, ISC, Apache-2.0, BSD-2/3-Clause, BlueOak-1.0.0, (MIT OR CC0-1.0), Python-2.0, MPL-2.0, CC-BY-4.0 (caniuse-lite data) | `"license"` field of every `package.json` under `/usr/local/lib/node_modules/bids-validator` | yes | keep |

## SPM 26.10.01 (`/opt/spm`)

| Component | Version | Licence | Evidence | In image | Action |
|---|---|---|---|---|---|
| SPM (code, toolboxes, matlabbatch, @gifti, @xmltree ...) | 26.10.01 | FREE, GPL-2.0-or-later | `/opt/spm/LICENCE` (GPL-2 text) + `/opt/spm/README.md`: "either version 2 of the License, or (at your option) any later version" | yes | keep; `licenses/SPM-GPL-2.0.txt` |
| SPM templates: `tpm/TPM.nii` (IXI), `tpm/mask_ICV.nii`, `canonical/*` (MNI/ICBM), `toolbox/DARTEL/icbm152.nii` (ICBM 2009c, MIT-style McGill notice), OldNorm/OldSeg/FieldMap templates | 26.10.01 | FREE as part of SPM's GPL distribution; upstream notices in `/opt/spm/spm_templates.md` | `spm_templates.md`. `mask_ICV.nii` is not a Neuromorphometrics derivative: 65 367 of its voxels lie outside the labels | yes | keep (bidspm's default first-level mask is `mask_ICV.nii`) |
| **Neuromorphometrics labels** `tpm/labels_Neuromorphometrics.nii/.xml` | 1.0 | **RESTRICTIVE: CC BY-NC**, "provided by Neuromorphometrics, Inc. under academic subscription" | `labels_Neuromorphometrics.xml` `<licence>CC BY-NC</licence>`; `spm_templates.md` | **no** | **removed**; results labelling degrades to a warning (below) |
| **TSSS toolbox** `toolbox/TSSS` | 26.10.01 | **RESTRICTIVE**: "permitted for non-commercial use" | header of `toolbox/TSSS/tsss_spm_enm.m` and its private files | **no** | **removed** (MEG only) |
| **CTF MEG readers** `external/ctf` | 1.3 | **UNCLEAR/custom**: MISL grants permission "with FieldTrip and SPM" only; `readCTFds.m`: "do not redistribute it without permission from CTF Systems Inc." | `external/ctf/COPYING`, `readCTFds.m` header | **no** | **removed** (MEG only) |
| **RICOH MEG reader** `external/ricoh_meg_reader` | 1.0 | **RESTRICTIVE: proprietary EULA** | `README.txt`, `EULA for RICOH MEG Reader Toolbox.pdf` | **no** | **removed** (MEG only) |
| **YOKOGAWA MEG reader** `external/yokogawa_meg_reader` | 1.5 | **RESTRICTIVE: proprietary EULA** | `README.txt`, `EULA for YOKOGAWA MEG Reader Toolbox.pdf` | **no** | **removed** (MEG only) |
| **Brainstorm files** `external/mne/mne_block_diag.m`, `toolbox/MEEGtools/private/{process_fooof,bst_prctile,macro_method}.m` | - | **UNCLEAR**: GPL header plus "FOR RESEARCH PURPOSES ONLY" | file headers | **no** | **removed** (M/EEG only) |
| **File Exchange helpers without licence** `external/fieldtrip/external/fileexchange/{arrow,keep,stlwrite,uimage,uimagesc}.m` | - | **UNCLEAR/NONE** (no `.license` file, no licence in header) | directory listing, headers | **no** | **removed** (plotting helpers, M/EEG) |
| File Exchange helpers with licence (CalcMD5, DataHash, base64*, icp, load_acq, pan_tompkin, subtightplot, vtkwrite) | - | FREE, BSD-2-Clause / MIT | `*.license` next to each file | yes | keep |
| FieldTrip (`external/fieldtrip`) | SPM 26 copy | FREE, GPL-3.0 | `external/fieldtrip/COPYING` | yes | keep |
| MNE-MATLAB (`external/mne`) | SPM 26 copy | FREE, BSD-3-Clause | `external/mne/LICENSE.txt` | yes | keep (minus the Brainstorm file) |
| eeprobe / libeep (`external/eeprobe`) | SPM 26 copy | FREE, LGPL-3.0 (+ relinking addendum) | `LICENSE`, `LICENSE.addendum` | yes | keep |
| bemcp | SPM 26 copy | FREE, GPL-2.0-or-later | `external/bemcp/README` | yes | keep |
| bvrf_reader | SPM 26 copy | FREE, MIT | `external/fieldtrip/external/bvrf_reader/LICENSE` | yes | keep |
| `src/external`: TriangleMeshDistance, raytri, jsmn (MIT), nii2mesh (BSD-2-Clause), edt (GPL-3.0); miniz in @gifti (Unlicense) | SPM 26 copy | FREE | `LICENSE` in each dir; `miniz.c` header | yes | keep |
| MACS toolbox (`toolbox/MACS`, from bidspm's submodule) | v1.3-28 | FREE, GPL-3.0 | `toolbox/MACS/LICENSE.md` | yes | keep |

## bidspm v4.0.0 (`/home/neuro/bidspm`)

| Component | Version | Licence | Evidence | In image | Action |
|---|---|---|---|---|---|
| bidspm (src, Python CLI, mancoreg, lib/utils range/unfold/iqr_method) | v4.0.0 | FREE, GPL-3.0 (no "or later" statement: treated as GPL-3.0-only) | `LICENSE` (GPL-3 text), `CITATION.cff` `license: GPL-3.0`, `pyproject.toml`; iqr_method from spmup (GPL-3.0, GitHub API) | yes | keep; `licenses/bidspm-GPL-3.0.txt` |
| bidspm report templates `src/reports` | v4.0.0 | FREE, CC0-1.0 | `src/reports/LICENSE` | yes | keep |
| bids-matlab | v0.2.0-55 | FREE, MIT | `lib/bids-matlab/LICENSE` | yes | keep |
| CPP_ROI (code) + MarsBaR | v0.4.0-13 | FREE, GPL-3.0 (MarsBaR GPL-2.0) | `lib/CPP_ROI/LICENSE`, `marsbar/mars_licence.man` | yes | keep |
| MACS | v1.3-28 | FREE, GPL-3.0 | `lib/MACS/LICENSE.md` | yes | keep |
| octache + JSONio + mustache spec | 0.1.0-54 | FREE, MIT | `lib/octache/LICENSE`, `lib/JSONio/LICENSE`, `spec/LICENSE` | yes | keep |
| brain_colours | 68f9a62 | FREE, ODC-By-1.0 (attribution: Cyril Pernet) | `lib/brain_colours/LICENSE` | yes | keep |
| panel | 2.14 | FREE, BSD-style (Ben Mitch) | `lib/panel-2.14/license.txt` | yes | keep |
| slice_display | 4326779 | FREE, MIT | `lib/slice_display/LICENSE` | yes | keep |
| riksneurotools | 10ccc1f | FREE, GPL-3.0 | `lib/riksneurotools/LICENSE` | yes | keep |
| spm_2_bids | v0.3.0-103 | FREE, GPL-3.0 | `lib/spm_2_bids/LICENSE` | yes | keep |
| **AAL3 atlas** `CPP_ROI/atlas/AAL3` | v1 | **UNCLEAR/NONE**: no licence file; no licence found upstream | no LICENSE in the folder; web search found none | **no** | **removed** |
| **Glasser HCP-MMP1.0 (volumetric)** `CPP_ROI/atlas/Glasser` | - | **RESTRICTIVE**: derived from HCP data, under the WU-Minn HCP Open Access Data Use Terms (MNE docs: "license terms that restrict its use") | `Glasser/README.md` (source: figshare 3501911); BALSA/MNE | **no** | **removed** |
| **HCPex** `CPP_ROI/atlas/HCPex` (nested git module) | v1.0/1.1 | **UNCLEAR**: a GPL-3.0 LICENSE file, but an extension of HCP-MMP1.0, which carries the HCP data use terms | `HCPex/LICENSE`, `HCPex/README.md` | **no** | **removed** |
| **visfAtlas** `CPP_ROI/atlas/visfAtlas` | - | **UNCLEAR/NONE**: citation request only | `visfAtlas/README.md` | **no** | **removed** |
| **Wang visual topography atlas** `CPP_ROI/atlas/visual_topography_probability_atlas(.zip)`, `space-MNI_seg-wang_dseg.xml` | v4 (2014) | **UNCLEAR/NONE**: citation request only; no licence from Princeton NAPL | README; web search | **no** | **removed** |
| **Yeo 7 networks** `CPP_ROI/atlas/yeo_7networks` | - | **UNCLEAR**: "imported from spm_up", provenance unstated; unused by bidspm | README | **no** | **removed** |
| **Neuromorphometrics label list** `CPP_ROI/atlas/space-IXI549Space_desc-neuromorphometrics_dseg.csv` | - | **RESTRICTIVE** (derived from the CC BY-NC labels) | file content | **no** | **removed** |
| **cprintf.m** (lib/utils, Yair Altman) | 2009 | **UNCLEAR**: "License to use and modify ... granted" -- no redistribution grant | header | **no** | **removed** (only called on MATLAB; Octave uses fprintf) |
| **renameStructField.m** (lib/utils) | 2013 | **UNCLEAR/NONE**: "Copyright The MathWorks, Inc.", no licence | header | **no** | **replaced** by our own GPL rewrite (`bidspm_overrides/lib/utils/renameStructField.m`) |
| **resize_img.m** (lib/utils, J. Ashburner / I. Nimmo-Smith / G. Ridgway "gems") | - | **UNCLEAR/NONE** | header | **no** | **removed** (only the lesion workflow uses it; not used by this runner) |
| **plot_power_spectra_of_GLM_residuals.m** (W. Olszowy) | 2018 | **UNCLEAR/NONE** | header | **no** | **removed** (unused) |
| bidspm/CPP_ROI/bids-matlab/... `tests/` and `demos/` (incl. MoAE test data, bids-examples) | v4.0.0 | **UNCLEAR** for the data; not needed at run time | - | **no** | **removed** |
| git history of the checkout (`.git`, incl. CPP_ROI's full history with every atlas above and the HCPex module) | - | as above | `.git/modules/lib/CPP_ROI/modules/atlas/HCPex` | **no** | **removed**; an empty repo stands in (bidspm reads branch/commit for reports) |

## Our own files

| Component | Licence | Notes |
|---|---|---|
| `bidspm_overrides/`, `containers/dockerfile/patches/` (MRI-Lab Graz) | GPL-3.0 (modifications of bidspm, so the same licence) | in the image |
| `containers/dockerfile/licenses/NOTICE` | - | credits, licence list, GPL source offer; `/usr/share/doc/spm-bids-runner/NOTICE` |

The rest of the runner repository (GUI, CLI) is not in the image and has no LICENSE file yet; that is the
owner's decision.

## SPDX for the image

`org.opencontainers.image.licenses="GPL-3.0-only"`: the program in the image is bidspm (GPL-3.0, no "or later"
grant) combined with SPM (GPL-2.0-or-later, so usable under GPL-3.0) and Octave (GPL-3.0-or-later); the
combination can only be conveyed under GPL-3.0. Permissively licensed parts (MIT/BSD/...) keep their notices
and are listed in `NOTICE`; the Debian base packages keep theirs in `/usr/share/doc/*/copyright`.

## Atlases without a licence problem

None of the atlases bidspm knows (`aal`, `glasser`, `hcpex`, `neuromorphometrics`, `visfatlas`, `wang`,
`anatomy_toobox`) could be kept. What still works: first-level/group statistics, contrasts, BMS, results export
(tables are left without region labels, with a `labelActivations` WARNING). What needs your own atlas: ROI
creation (`bidspm create_roi`) and region labels in results tables. See README, "Atlases".
