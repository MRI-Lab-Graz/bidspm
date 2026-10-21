# Student walkthrough: from raw data to a group result

This walkthrough takes one real study (study 141, task `crom`, fMRIPrep output in MNI152NLin2009cAsym space) through
the whole BIDSPM Runner GUI: create a project, build a model with the wizard, check readiness, run
smooth + stats + dataset, and look at the outputs. It was done for real, on a scratch copy of three subjects
(`sub-141A332C`, `sub-141A891C`, `sub-141B201C`), in a fresh clone following the README. The paths in the screenshots
(`/data/local/tmp_big/walkthrough/...`) are that scratch copy; yours will differ.

Three subjects is a demonstration, not an analysis: a group t-test with n=3 has 2 degrees of freedom.

What you need first (details in the README, "Prerequisites"): Docker with your user in the `docker` group (or Apptainer),
about 3.5 GB for the image, about 0.7 GB for the Python environment, a BIDS dataset (raw) and its fMRIPrep output.
Time on our machine (32 cores, 3 subjects in parallel, about 1000 volumes each, the default Octave engine):
smoothing about 1 minute, model estimation about 28 minutes, group level a few seconds.

## 1. Install and start

```bash
git clone https://github.com/MRI-Lab-Graz/bidspm.git
cd bidspm
# the image: pull it once it is published, or build it (5 minutes cold, needs internet)
docker build -f containers/dockerfile/dockerfile -t ghcr.io/mri-lab-graz/spm-bids-runner:latest .
./scripts/setup.sh        # uv builds .bidspm (own Python 3.12 + the packages); about 5 s with a warm uv cache
./scripts/start_gui.sh    # port 5100; BIDSPM_PORT=5101 ./scripts/start_gui.sh if it is taken
```

The start script prints a "Pre-flight check" and then `Open in browser: http://localhost:5100`. On a server over SSH, forward
the port (`ssh -L 5100:localhost:5100 you@server`) and open `http://localhost:5100` on your own machine. The GUI has no login:
never expose the port.

Notes from doing it:

- `./scripts/setup.sh` rewrites the tracked file `uv.lock` (git shows ` M uv.lock` right after a clean setup). Do not commit
  it; `git checkout uv.lock` before `git pull`.
- The start-up pre-flight check covers the program itself, not Docker and not the image. Whether Docker and the image are
  usable is only reported by the readiness check later (`container` warning, `image_missing`). Check once yourself:
  `docker images ghcr.io/mri-lab-graz/spm-bids-runner`.
- The `config/config.json` copy in the README (`cp config/config.example.json config/config.json`) is for command-line use only.
  The GUI did not need it.

## 2. Create a project

Projects page, "New Project". Fill in the name, the BIDS folder (raw data), the fMRIPrep folder and an output folder.
The space is read from the fMRIPrep folder (here MNI152NLin2009cAsym). Leave the container type at Docker and the image
field empty: the default image is used.

![New project dialog](walkthrough/01_new_project.png)

"Create Project" takes you straight to the analysis page, at the Model stage. The analysis page has four stages:
Folders, Model, Options, Review and run.

![Analysis page right after creating the project](walkthrough/02_after_create.png)

## 3. Folders stage

Check what you entered. The working directory is where everything is written (derivatives, models, logs). The task list is
read from the BIDS folder: tick `crom`. FWHM is the smoothing kernel in mm (6 here). "Advanced" holds an optional separate
derivatives folder (it defaults to the working directory).

![Folders stage](walkthrough/03_folders.png)

## 4. Model stage: the model wizard

"Create Model" opens the wizard, a five-step stepper. Next is blocked, with a reason, until a step is complete.

**Step 1, task and conditions.** The wizard reads the events files of all subjects. We untick `fixation` (baseline) and
`button_press` (zero duration) and keep `item`, `rating` and `verbal_response`.

![Wizard step 1](walkthrough/04_wizard_task.png)

**Step 2, recipes.** Click a recipe card to add it. We use "Only valid/correct trials": condition `item`, column
`response_validity`, keep rows where it equals `valid`. Choose all three fields; the first values in the lists are not
meaningful (see the gotchas below). The right-hand summary now shows `valid_item.item` instead of `trial_type.item`, and
a warning that trials with `response_validity = invalid` are not modelled. That is intended.

![Wizard step 2](walkthrough/05_wizard_recipes.png)

**Step 3, nuisance.** Choose a confound preset. The default is `none`; we pick `motion6` (the six realignment parameters from
fMRIPrep).

![Wizard step 3](walkthrough/06_wizard_nuisance.png)

**Step 4, contrasts.** One contrast per regressor is generated. Under "Add a comparison" we add `item_gt_rating`
(positive `valid_item.item`, negative `trial_type.rating`). Anything fancier (weights, F contrasts) goes through the
contrast builder on the analysis page.

![Wizard step 4](walkthrough/07_wizard_contrasts.png)

**Step 5, review and save.** Give the model a name; the save path follows it
(`<working directory>/models/<name>.json`). "Check readiness" checks this model against your data before you save
(here: ready). "Save and open" writes the file, makes it the project's model and returns to the analysis page.

![Wizard step 5](walkthrough/08_wizard_review.png)

![After saving: the analysis page opens at Review and run](walkthrough/09_after_save.png)

## 5. Options stage

Actions: tick **Smooth**, **Stats** and **Dataset** (the defaults are Smooth and Stats only). Smooth makes the
smoothed images, Stats fits the model per subject, Dataset runs the group level over all selected subjects. Report and BMS
are separate options.

![Options stage](walkthrough/10_options.png)

"Select Participants" shows who has output already and who is missing; by default all participants run. Here: three
missing, three selected.

![Select Participants](walkthrough/11_participants.png)

Execution options: "Parallel subjects" is how many subjects are estimated at once (about 4 GB of memory each; "Suggest"
proposes a number). "Force Rerun" redoes subjects whose output already exists. For "SPM Results export", see section 8.

Careful: the options you tick are only part of the project once you click Save or Save & Run. If you reload the page
first, the checkbox is gone again.

## 6. Review and run: the readiness check

"Check readiness" checks the folders, the dataset validator, the model and every selected subject (events, preprocessed
BOLD, confounds). It ended with `warnings`: 28 BIDS validator warnings (missing authors, undescribed events columns),
which do not stop a run. Errors would block Run and name the subject and file. Warnings are fine, errors are not.

![Readiness check](walkthrough/12_readiness.png)

## 7. Save & Run

"Save & Run" saves the project and starts the run. The terminal log follows it live. The command line it runs is printed
first (`bidspm.py --action smooth stats dataset ...`), so you can repeat the same run without the GUI.

![Run started](walkthrough/13_run_started.png)

During estimation the log shows chunks and ReML iterations, and "Run issues" collects warnings. These are expected for
fMRIPrep input in this image: "Slice timing information was missing" (fMRIPrep drops `SliceTiming`; the start time is used),
"Goodness of fit / Information criterion not implemented in Octave", and "overwriting directory" when a stage is rerun.

![Run in the middle of estimation](walkthrough/14_run_midway.png)

It finished with `Pipeline completed successfully, Subjects processed: 3, Subjects failed: 0, Actions completed:
dataset, smooth, stats` and exit code 0. `python scripts/check_run_log.py <logfile>` reported 0 problem lines.

![Run finished](walkthrough/15_run_done.png)

Things to know while it runs:

- Stop works (the run ended within seconds with exit code 1). We stopped one run during smoothing and found incomplete
  `bidspm-preproc/` output afterwards; we deleted it before running again and did not test whether a rerun would have
  skipped a half-written file. Do the same: delete `bidspm-preproc/sub-*/` of the stopped run.
- If you reload the page while a run is going, the terminal shows "IDLE" and an empty log although the run continues. The
  run's log file is in `<working directory>/logs/` (its path is the second line of the terminal log).

## 8. Optional: SPM Results export

The "SPM Results export" switch (slower, optional) makes the stats step also run SPM's Results step: a thresholded results
table (csv) per contrast, at subject and dataset level (FWE p < 0.05 by default). No png images or montages are written in
this container (SPM cannot draw headless here, and the NIDM export needs Java, which the image does not contain). It is off by default because it costs about a third of the per-subject
time on short runs. The Report action needs it and turns it on by itself.

Tick it when you want SPM's own thresholded tables and pictures per contrast, or the HTML report. Leave it off when you
only need the statistic images (`spmT_*.nii`, `con_*.nii`) to view or threshold in your own viewer, which is the normal case
while you are still building and checking a model.

Region labels need your own atlas. The image contains no atlas (licence reasons), so results tables have no
brain-region names, and the readiness check says so: "The report's results tables will have no brain-region labels: the
spm-bids-runner image includes no atlas (licence reasons)". That is expected. If you need labels, build a derived image
with an atlas you are allowed to use (README, "Atlases").

Checked on three study 141 subjects: the export adds roughly 25-40 s per subject and about 1-1.5 min for the dataset level, and
writes the csv tables under `bidspm-stats` (subject) and `bidspm-stats/derivatives/bidspm-groupStats` (dataset). The screenshots of this second run:

![Options with Results export, Report and Force Rerun ticked](walkthrough/16_options_results.png)

![Readiness check with the atlas notice](walkthrough/17_readiness_results.png)

![Second run finished: stats, dataset and HTML report](walkthrough/18_run2_done.png)

## 9. Look at the outputs

Everything is under the working directory:

```
output/
  models/crom_valid_items.json        your model
  bidspm-preproc/sub-*/ses-1/func/    smoothed images (..._desc-smth6_bold.nii)
  bidspm-stats/sub-*/task-crom_space-..._FWHM-6/
      SPM.mat, beta_*.nii, con_*.nii, spmT_*.nii, mask.nii, ..._onsets.tsv
  bidspm-stats/derivatives/bidspm-groupStats/
      sub-ALL_task-crom_..._node-dataset_contrast-itemGtRating/   SPM.mat, con_0001.nii, spmT_0001.nii, ...
      ... one folder per contrast (rating, verbalResponse, validItemItem, itemGtRating)
  logs/  options/  reports/
```

The **group results** are the `spmT_0001.nii` (t map) and `con_0001.nii` (mean contrast) in each
`bidspm-groupStats/sub-ALL_..._contrast-<name>/` folder. The GUI has no image viewer: open them in SPM, FSLeyes, MRIcroGL or
similar. The picture below is the unthresholded t map of `item_gt_rating` (spmT_0001.nii) over three subjects, drawn with a
few lines of nibabel and matplotlib on one subject's MNI reference image. It is only there to show what the file holds; with
n=3 (2 degrees of freedom) nothing in it is interpretable.

![Group t map, item_gt_rating, three subjects](walkthrough/20_group_tmap.png)

The per-subject folders hold the same files for the first level (8 contrasts: four per session plus four across sessions,
here identical because there is one session).

The Report action writes `reports/index.html` (group overview with a card per subject) and one `sub-*_report.html` per
subject (summary, contrast table, methods text for your manuscript).

![HTML report, group overview](walkthrough/19_report_index.png)

Known problems of the report in this version (found while doing this walkthrough): the subject pages render their main
content in a one-word-wide pale column in Chromium (a mis-nested `<nav>` in the page template), and the methods text still
contains the unfilled placeholders `{{version}}` and `{{designType}}` and says "SPM26 - 00.00". Read the numbers from the
files, not from the report, until that is fixed.

## 10. Small gotchas in the wizard

- After editing a text field or a comparison row, the first click on the next button can be swallowed (probably the edit re-builds the
  preview while you click). If nothing happens, click again. We hit this on "Next" after naming a
  comparison and on "Check readiness" after naming the model.
- In the "Only valid/correct trials" recipe, the column list starts with the alphabetically first column (`ai_rating`), and the
  value list for it holds 100 numbers; the red message "value '1.15' cannot be used in the valid_only recipe" shows up at once.
  Pick the column you mean (`response_validity`) and the message disappears.
- The wizard saves the model in `<working directory>/models/`, not `<working directory>/derivatives/models/` as the README's
  "Basic usage" says.
