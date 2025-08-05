#!/usr/bin/env python3
"""
MATLAB Runtime Performance Test for BIDSPM
Automated performance comparison between Octave and MATLAB Runtime containers
"""

import subprocess
import time
import json
from pathlib import Path

def run_container_test(container_config, test_name):
    """Run performance test with specified container"""
    print(f"\n🧪 Testing {test_name}...")
    
    start_time = time.time()
    
    # Run BIDSPM model specification
    cmd = [
        "python3", "bidspm.py",
        "/raw", "/derivatives", "participant",
        "--model", "/raw/model.json",
        "--task", "faces",
        "--space", "MNI152NLin2009cAsym",
        "--container", container_config,
        "--action", "stats"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        elapsed_time = time.time() - start_time
        
        # Parse output for performance metrics
        output_lines = result.stdout.split('\n')
        spm_times = [line for line in output_lines if 'SPM' in line and ('sec' in line or 'minute' in line)]
        
        return {
            "container": test_name,
            "total_time": elapsed_time,
            "returncode": result.returncode,
            "spm_performance": spm_times,
            "success": result.returncode == 0,
            "stderr": result.stderr[:500] if result.stderr else ""
        }
        
    except subprocess.TimeoutExpired:
        return {
            "container": test_name,
            "total_time": 300,
            "returncode": -1,
            "error": "Timeout after 5 minutes",
            "success": False
        }

def main():
    """Run automated performance comparison"""
    print("🚀 BIDSPM MATLAB Runtime Performance Test")
    print("=" * 50)
    
    # Test configurations
    tests = [
        ("container.json", "Octave Container"),
        ("container_matlab_ultra.json", "MATLAB Runtime Ultra")
    ]
    
    results = []
    
    for config_file, test_name in tests:
        if Path(config_file).exists():
            result = run_container_test(config_file, test_name)
            results.append(result)
            
            if result["success"]:
                print(f"✅ {test_name}: {result['total_time']:.1f}s")
            else:
                print(f"❌ {test_name}: Failed ({result.get('error', 'Unknown error')})")
        else:
            print(f"⚠️  Config {config_file} not found - skipping {test_name}")
    
    # Performance comparison
    if len(results) >= 2:
        octave_time = next((r["total_time"] for r in results if "Octave" in r["container"]), None)
        matlab_time = next((r["total_time"] for r in results if "MATLAB" in r["container"]), None)
        
        if octave_time and matlab_time:
            speedup = octave_time / matlab_time
            print("\n📊 Performance Summary:")
            print(f"   Octave Container: {octave_time:.1f}s")
            print(f"   MATLAB Runtime:   {matlab_time:.1f}s")
            print(f"   Speedup Factor:   {speedup:.1f}x")
            
            if speedup > 2.0:
                print("🎉 MATLAB Runtime shows significant performance improvement!")
            elif speedup > 1.2:
                print("✅ MATLAB Runtime shows moderate performance improvement")
            else:
                print("⚠️  Performance improvement minimal")
    
    # Save detailed results
    with open("performance_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print("\n📄 Detailed results saved to performance_test_results.json")
    return results

if __name__ == "__main__":
    main()
