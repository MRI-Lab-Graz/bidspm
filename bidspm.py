#!/usr/bin/env python3
"""
BIDSPM Runner - CLI Entry Point

This is a thin CLI wrapper that parses arguments and delegates to the core Pipeline.
All business logic is in lib/core.py to avoid duplication with bidspm_gui.py.
"""

import argparse
import sys
from pathlib import Path

from lib import (
    Pipeline, PipelineOptions, PipelineResult,
    detect_matlab_environment, check_feature_availability,
    discover_subjects, discover_tasks, estimate_processing_time,
    log_debug
)
from lib.config import load_config
from lib.utils import DEBUG


# Default config file paths
CONFIG_FILE = "config/config.json"
CONTAINER_CONFIG_FILE = "containers/container.json"


def show_help():
    """Display comprehensive help information."""
    help_text = """
🧠 BIDSPM Runner - BIDS-StatsModel Pipeline Tool

DESCRIPTION:
    A Python wrapper for running BIDS-StatsModel statistical pipelines using 
    containerized BIDSPM or local MATLAB/Octave. This tool manages the entire 
    pipeline from smoothing preprocessed data to running statistical analyses.

USAGE:
    python bidspm.py [OPTIONS] --action ACTION [ACTION ...]

REQUIRED ARGUMENTS:
    --action {smooth,stats,dataset}
                          Actions to perform (specify one or more):
                          • smooth  : Smooth preprocessed fMRI data
                          • stats   : Run subject-level statistical analysis
                          • dataset : Run group-level statistical analysis

OPTIONAL ARGUMENTS:
    -h, --help           Show this help message and exit
    -s, --settings       Path to configuration JSON file (default: config/config.json)
    -c, --container      Path to container config file (default: auto-detect)
    -m, --model          Path to BIDS-StatsModel JSON file (overrides config)
    --pilot              Test mode: process only one random subject
    --skip-modelvalidation
                         Skip validation of BIDS-StatsModel JSON
    --local              Use local BIDSPM installation instead of containers
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
    
    # Pilot test (single random subject)
    python bidspm.py --action smooth --pilot
    
    # Preview commands without running
    python bidspm.py --action smooth stats --dry-run
    
    # Check available subjects
    python bidspm.py --list-subjects
    
    # Estimate time for full run
    python bidspm.py --action smooth stats --estimate-time
    
    # Use local MATLAB/Octave
    python bidspm.py --local --action smooth

ENVIRONMENT DETECTION:
    Local execution (--local) automatically detects:
    • Licensed MATLAB (full features)
    • GNU Octave (most features)
    • SPM12 Standalone (limited features - compiled only)
    
    Standalone limitations:
    • Cannot run custom scripts
    • ROI analysis may not work
    • Some statistical models unsupported

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
    
    # Actions
    parser.add_argument('--action', nargs='+', 
                       choices=['smooth', 'stats', 'dataset'],
                       help='Actions to perform')
    
    # Flags
    parser.add_argument('--pilot', action='store_true',
                       help='Process only one random subject')
    parser.add_argument('--skip-modelvalidation', action='store_true',
                       help='Skip BIDS-StatsModel validation')
    parser.add_argument('--local', action='store_true',
                       help='Use local MATLAB/Octave instead of containers')
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
                       help='Check MATLAB/container environment and exit')
    
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


def handle_check_environment(use_local: bool):
    """Check and display environment capabilities."""
    print("\n🔍 Environment Check")
    print("=" * 50)
    
    if use_local:
        caps = detect_matlab_environment()
        
        print(f"\n  Environment: {caps.environment.value}")
        if caps.path:
            print(f"  Path: {caps.path}")
        if caps.version:
            print(f"  Version: {caps.version}")
        
        print("\n  Capabilities:")
        print(f"    Run scripts: {'✅' if caps.can_run_arbitrary_scripts else '❌'}")
        print(f"    Compile MEX: {'✅' if caps.can_compile_mex else '❌'}")
        print(f"    Toolboxes: {'✅' if caps.can_use_toolboxes else '❌'}")
        print(f"    Parallel: {'✅' if caps.can_use_parallel else '❌'}")
        
        if caps.limitations:
            print("\n  ⚠️  Limitations:")
            for limit in caps.limitations:
                print(f"    • {limit}")
        
        features = check_feature_availability(caps, using_container=False)
        print("\n  Feature Availability:")
        print(f"    Smooth: {'✅' if features.smooth else '❌'}")
        print(f"    Stats (subject): {'✅' if features.stats_subject else '❌'}")
        print(f"    Stats (dataset): {'✅' if features.stats_dataset else '❌'}")
        print(f"    ROI Analysis: {'✅' if features.roi_analysis else '❌'}")
    else:
        # Container check
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
        handle_check_environment(args.local)
    
    if args.estimate_time:
        if not args.action:
            print("❌ --estimate-time requires --action")
            sys.exit(1)
        handle_estimate_time(config_file, args.action)
    
    # Require action for actual execution
    if not args.action:
        print("❌ Error: --action argument is required")
        print("   Please specify at least one action: smooth, stats, dataset")
        print("\nUse --help for more information\n")
        sys.exit(1)
    
    # Build pipeline options
    options = PipelineOptions(
        actions=args.action,
        config_file=config_file,
        container_config_file=args.container,
        model_file=args.model,
        pilot=args.pilot,
        skip_validation=args.skip_modelvalidation,
        local=args.local,
        force=args.force,
        dry_run=args.dry_run,
        debug=args.debug,
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
        
        if result.errors:
            print("\n❌ Errors:")
            for e in result.errors:
                print(f"   • {e}")
        
        if result.dry_run_commands:
            print("\n🔍 Commands that would be executed:")
            for cmd in result.dry_run_commands:
                print(f"   {cmd[:100]}...")
        
        print()
        sys.exit(0 if result.success else 1)
        
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
