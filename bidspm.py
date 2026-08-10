#!/usr/bin/env python3
"""
BIDSPM Runner - CLI Entry Point

This is a thin CLI wrapper that parses arguments and delegates to the core Pipeline.
All business logic is in lib/core.py to avoid duplication with bidspm_gui.py.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from lib import (
    Pipeline, PipelineOptions, PipelineResult,
    discover_subjects, discover_tasks, estimate_processing_time,
    log_debug, run_bms
)
from lib.config import load_config


# Default config file paths
CONFIG_FILE = "config/config.json"
CONTAINER_CONFIG_FILE = "containers/container.json"


def show_help():
    """Display comprehensive help information."""
    help_text = """
🧠 BIDSPM Runner - BIDS-StatsModel Pipeline Tool

DESCRIPTION:
    A Python wrapper for running BIDS-StatsModel statistical pipelines using
    containerized BIDSPM (Docker or Apptainer). This tool manages the entire
    pipeline from smoothing preprocessed data to running statistical analyses.

USAGE:
    python bidspm.py [OPTIONS] --action ACTION [ACTION ...]

REQUIRED ARGUMENTS:
    --action {smooth,stats,dataset,report,bms}
                          Actions to perform (specify one or more):
                          • smooth  : Smooth preprocessed fMRI data
                          • stats   : Run subject-level statistical analysis
                          • dataset : Run group-level statistical analysis
                          • report  : Generate HTML QC/results report (no MATLAB needed)
                          • bms     : Bayesian Model Selection across competing models
                                      in --models-dir (requires container; each model
                                      must already have --action stats run for it)

OPTIONAL ARGUMENTS:
    -h, --help           Show this help message and exit
    -s, --settings       Path to configuration JSON file (default: config/config.json)
    -c, --container      Path to container config file (default: auto-detect)
    -m, --model          Path to BIDS-StatsModel JSON file (overrides config)
    --models-dir         Directory of competing models to compare (--action bms only)
    --pilot              Test mode: process only one random subject
    --skip-modelvalidation
                         Skip validation of BIDS-StatsModel JSON
    --smooth-backend     Smoothing implementation: "fast" (default, parallel
                         nibabel/scipy, no MATLAB) or "spm" (MATLAB/SPM)
    --stats-workers      Number of subjects to process concurrently for
                         smooth/stats. Default 4. Set to 1 to disable
                         parallelism (e.g. for limited container concurrency).
    --force              Force reprocessing even if output already exists
    --dry-run            Show commands without executing them
    --debug              Enable debug output
    --list-subjects      List available subjects and exit
    --list-tasks         List available tasks and exit
    --estimate-time      Estimate processing time and exit

EXAMPLES:
    # Get help
    python bidspm.py -h
    
    # Run complete pipeline
    python bidspm.py --action smooth stats dataset

    # Generate HTML reports after processing
    python bidspm.py --action report

    # Process then immediately generate reports
    python bidspm.py --action smooth stats dataset report
    
    # Pilot test (single random subject)
    python bidspm.py --action smooth --pilot
    
    # Preview commands without running
    python bidspm.py --action smooth stats --dry-run
    
    # Check available subjects
    python bidspm.py --list-subjects
    
    # Estimate time for full run
    python bidspm.py --action smooth stats --estimate-time

MORE INFORMATION:
    • GitHub: https://github.com/MRI-Lab-Graz/bidspm
    • BIDS-StatsModel: https://bids-standard.github.io/stats-models/
    """
    print(help_text)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="BIDSPM Runner - Run BIDS-StatsModel pipelines",
        add_help=False
    )
    
    # Help
    parser.add_argument('-h', '--help', action='store_true',
                       help='Show help message and exit')
    
    # Config files
    parser.add_argument('-s', '--settings', '--config',
                       help='Path to main configuration file')
    parser.add_argument('-c', '--container', '--container-config',
                       help='Path to container configuration file')
    parser.add_argument('-m', '--model', '--model-file',
                       help='Path to BIDS-StatsModel JSON file')
    parser.add_argument('--node-name', '--node_name',
                       dest='node_name',
                       help='Name of the BIDS model node to run')
    parser.add_argument('--name-by-confounds', action='store_true', dest='name_by_confounds',
                       help='Append confound strategy suffix to model node names before running stats '
                            '(prevents output-folder collisions when comparing confound strategies)')
    
    # Actions
    parser.add_argument('--action', nargs='+',
                       choices=['smooth', 'stats', 'dataset', 'report', 'bms'],
                       help='Actions to perform')
    parser.add_argument('--models-dir', '--models_dir',
                       dest='models_dir',
                       help='Directory of competing BIDS-StatsModel JSON files to compare '
                            '(required for --action bms; must contain only the models '
                            'being compared, bidspm globs every *.json in it)')
    parser.add_argument('--models', nargs='+', dest='models',
                       help='Model files to compare in BMS (alternative to --models-dir; '
                            'materializes a temp dir with _smdl.json copies at run time)')
    
    # Flags
    parser.add_argument('--pilot', action='store_true',
                       help='Process only one random subject')
    parser.add_argument('--skip-modelvalidation', action='store_true',
                       help='Skip BIDS-StatsModel validation')
    parser.add_argument('--smooth-backend', choices=['spm', 'fast'], default='fast',
                       help='Smoothing implementation: "fast" (default, parallel '
                            'nibabel/scipy, no MATLAB) or "spm" (MATLAB/SPM)')
    parser.add_argument('--stats-workers', type=int, default=4,
                       help='Number of subjects to process concurrently for smooth/stats. '
                            'Default 4. Set to 1 to disable parallelism (e.g. for limited '
                            'container concurrency).')
    parser.add_argument('--force', action='store_true',
                       help='Force reprocessing of existing outputs')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show commands without executing')
    parser.add_argument('--debug', '-v', action='store_true',
                       help='Enable debug output')
    
    # Discovery commands
    parser.add_argument('--list-subjects', action='store_true',
                       help='List available subjects and exit')
    parser.add_argument('--list-tasks', action='store_true',
                       help='List available tasks and exit')
    parser.add_argument('--estimate-time', action='store_true',
                       help='Estimate processing time and exit')
    parser.add_argument('--check-environment', action='store_true',
                       help='Check container environment and exit')
    
    return parser.parse_args()


def handle_list_subjects(config_file: str):
    """List available subjects and exit."""
    config = load_config(config_file)
    subjects = discover_subjects(config)
    
    print(f"\n📋 Available subjects ({len(subjects)} total):")
    print("-" * 40)
    
    if subjects:
        for s in subjects:
            print(f"  • {s}")
    else:
        print("  No subjects found in fMRIPrep derivatives")
    
    print()
    sys.exit(0)


def handle_list_tasks(config_file: str):
    """List available tasks and exit."""
    config = load_config(config_file)
    tasks = discover_tasks(config.BIDS_DIR)
    
    print(f"\n📋 Available tasks ({len(tasks)} total):")
    print("-" * 40)
    
    if tasks:
        for t in tasks:
            print(f"  • {t}")
    else:
        print("  No tasks found in BIDS directory")
    
    print()
    sys.exit(0)


def handle_estimate_time(config_file: str, actions: list):
    """Estimate processing time and exit."""
    config = load_config(config_file)
    subjects = config.SUBJECTS or discover_subjects(config)
    tasks = config.TASKS
    
    estimate = estimate_processing_time(subjects, actions, tasks)
    
    print(f"\n⏱️  Processing Time Estimate")
    print("=" * 40)
    print(f"  Subjects: {estimate['subjects']}")
    print(f"  Tasks: {estimate['tasks']}")
    print(f"  Actions: {', '.join(actions)}")
    print("-" * 40)
    
    for action, minutes in estimate['breakdown'].items():
        print(f"  {action}: ~{minutes} min")
    
    print("-" * 40)
    print(f"  TOTAL: ~{estimate['formatted']}")
    print(f"\n  Note: {estimate['note']}\n")
    
    sys.exit(0)


def handle_check_environment():
    """Check and display container environment capabilities."""
    print("\n🔍 Environment Check")
    print("=" * 50)

    import shutil
    import subprocess

    docker = shutil.which("docker")
    apptainer = shutil.which("apptainer")

    print("\n  Container Runtimes:")

    if docker:
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            if result.returncode == 0:
                print("    Docker: ✅ Available and running")
            else:
                print("    Docker: ⚠️  Installed but not running")
        except:
            print("    Docker: ⚠️  Installed but check failed")
    else:
        print("    Docker: ❌ Not found")

    if apptainer:
        print("    Apptainer: ✅ Available")
    else:
        print("    Apptainer: ❌ Not found")

    if docker or apptainer:
        print("\n  All features available via container execution")

    print()
    sys.exit(0)


def _handle_report(config_file: str, args, processed_subjects: Optional[List[str]] = None) -> None:
    """Generate HTML reports from existing bidspm derivatives.

    ``processed_subjects``, when given, restricts which per-subject report
    pages get (re)written to just the subjects touched by the pipeline run
    that just finished -- e.g. a --pilot run should not rewrite every other
    subject's report page. ``None`` (report-only invocations, with no
    pipeline run behind them) renders every subject.
    """
    from lib.report_generator import generate_reports

    config = load_config(config_file)
    subjects = config.SUBJECTS or discover_subjects(config)

    model_name = ""
    if args.model or config.MODELS_FILE:
        import json as _json
        mf = args.model or config.MODELS_FILE
        try:
            with open(mf) as f:
                m = _json.load(f)
            model_name = m.get("Name", Path(mf).stem)
        except Exception:
            model_name = Path(mf).stem if mf else ""

    print("\n📄 Generating HTML reports…")
    index = generate_reports(
        derivatives=config.DERIVATIVES_DIR,
        tasks=config.TASKS,
        subjects=subjects or None,
        model_name=model_name,
        subjects_to_render=processed_subjects,
    )
    print(f"\n✅ Group index: {index}\n")


def _handle_bms(config_file: str, args) -> bool:
    """Run Bayesian Model Selection across the models in --models-dir or --models.

    Returns True on success. Requires container execution and a `stats` run
    already completed for every competing model (BMS compares their
    already-estimated SPM.mat files).
    """
    models = getattr(args, 'models', None)
    if not args.models_dir and not models:
        print("❌ --action bms requires --models-dir or --models")
        return False

    label = args.models_dir or f"{len(models)} model file(s)"
    print(f"\n🧮 Running Bayesian Model Selection ({label})…")
    config = load_config(config_file)
    result = run_bms(
        config_file=config_file,
        container_config_file=args.container,
        models_dir=args.models_dir,
        model_files=models,
        dry_run=args.dry_run,
        skip_validation=args.skip_modelvalidation,
        participant_label=config.SUBJECTS,
    )

    if result["dry_run_commands"]:
        print("\n🔍 Command that would be executed:")
        for cmd in result["dry_run_commands"]:
            print(f"   {cmd}")

    if result["success"]:
        print("✅ BMS completed successfully\n")
    else:
        print("❌ BMS failed")
        for e in result["errors"]:
            print(f"   • {e}")
        print()

    return result["success"]


def main():
    """Main entry point."""
    args = parse_arguments()
    
    # Enable debug mode
    if args.debug:
        import lib.utils
        lib.utils.DEBUG = True
    
    # Handle help
    if args.help or len(sys.argv) == 1:
        show_help()
        sys.exit(0)
    
    # Config file
    config_file = args.settings or CONFIG_FILE
    
    # Handle discovery commands (don't need actions)
    if args.list_subjects:
        handle_list_subjects(config_file)
    
    if args.list_tasks:
        handle_list_tasks(config_file)
    
    if args.check_environment:
        handle_check_environment()
    
    if args.estimate_time:
        if not args.action:
            print("❌ --estimate-time requires --action")
            sys.exit(1)
        handle_estimate_time(config_file, args.action)
    
    # Require action for actual execution
    if not args.action:
        print("❌ Error: --action argument is required")
        print("   Please specify at least one action: smooth, stats, dataset, report, bms")
        print("\nUse --help for more information\n")
        sys.exit(1)

    # Strip report/bms from pipeline actions — neither goes through the
    # per-subject/task Pipeline loop (report is pure Python; bms compares
    # already-estimated models across a --models-dir, not a single model).
    run_report = 'report' in args.action
    run_bms_action = 'bms' in args.action
    args.action = [a for a in args.action if a not in ('report', 'bms')]

    if not args.action and (run_report or run_bms_action):
        # No smooth/stats/dataset requested: skip the pipeline entirely.
        bms_ok = True
        if run_bms_action:
            bms_ok = _handle_bms(config_file, args)
        if run_report:
            _handle_report(config_file, args)
        sys.exit(0 if bms_ok else 1)

    # Build pipeline options
    options = PipelineOptions(
        actions=args.action,
        config_file=config_file,
        container_config_file=args.container,
        model_file=args.model,
        node_name=args.node_name,
        pilot=args.pilot,
        skip_validation=args.skip_modelvalidation,
        smooth_backend=args.smooth_backend,
        stats_workers=args.stats_workers,
        force=args.force,
        dry_run=args.dry_run,
        debug=args.debug,
        name_by_confounds=args.name_by_confounds,
    )
    
    # Create and run pipeline
    pipeline = Pipeline(options)
    
    try:
        result = pipeline.run()
        
        # Print summary
        print("\n" + "=" * 50)
        print("📊 Pipeline Summary")
        print("=" * 50)
        
        if result.success:
            print("✅ Pipeline completed successfully")
        else:
            print("⚠️  Pipeline completed with errors")
        
        print(f"   Subjects processed: {len(result.subjects_processed)}")
        print(f"   Subjects failed: {len(result.subjects_failed)}")
        print(f"   Actions completed: {', '.join(result.actions_completed) or 'none'}")
        print(f"   Log file: {result.log_file}")
        
        if result.warnings:
            print("\n⚠️  Warnings:")
            for w in result.warnings:
                print(f"   • {w}")

        if result.environment_notes and (not result.success or args.debug):
            print("\nℹ️  Environment Notes:")
            for note in result.environment_notes:
                print(f"   • {note}")
        
        if result.errors:
            print("\n❌ Errors:")
            for e in result.errors:
                print(f"   • {e}")
        
        if result.dry_run_commands:
            print("\n🔍 Commands that would be executed:")
            for cmd in result.dry_run_commands:
                print(f"   {cmd[:100]}...")
        
        print()

        # Run BMS after the pipeline completes -- it compares already-
        # estimated SPM.mat files across --models-dir, so any stats run
        # requested alongside it must finish first.
        bms_ok = True
        if run_bms_action:
            bms_ok = _handle_bms(config_file, args)

        # Generate HTML report after pipeline completes -- restrict to
        # subjects this run actually touched, so e.g. a --pilot run doesn't
        # rewrite every other subject's report page.
        if run_report:
            _handle_report(config_file, args, processed_subjects=result.subjects_processed)

        sys.exit(0 if (result.success and bms_ok) else 1)
        
    except KeyboardInterrupt:
        print("\n\n🛑 Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
