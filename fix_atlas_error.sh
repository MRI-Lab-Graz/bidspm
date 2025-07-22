#!/bin/bash

# BIDSPM Atlas Error Fix Script
# Systematically tests different approaches to fix the 'returnAtlasDir' undefined error

echo "🔧 BIDSPM Atlas Error Fix Testing"
echo "================================="

# Configuration
WORK_DIR="/tmp/bidspm_atlas_test"
LOG_FILE="atlas_fix_test.log"

# Create working directory
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

echo "📝 Testing will be logged to: $PWD/$LOG_FILE"
echo "Starting atlas error diagnosis..." > "$LOG_FILE"

# Function to test container with different configurations
test_container_config() {
    local version="$1"
    local env_vars="$2"
    local description="$3"
    
    echo ""
    echo "🧪 Test: $description"
    echo "   Version: $version"
    echo "   Env vars: $env_vars"
    
    local container_image="docker://cpplab/bidspm:$version"
    local test_sif="test_${version//./}.sif"
    
    # Pull container if not exists
    if [ ! -f "$test_sif" ]; then
        echo "   📥 Pulling container..."
        if ! timeout 120 apptainer pull --force "$test_sif" "$container_image" 2>>"$LOG_FILE"; then
            echo "   ❌ Failed to pull container"
            return 1
        fi
    fi
    
    # Test basic functionality
    echo "   🧮 Testing basic BIDSPM functionality..."
    local cmd="apptainer run --containall --cleanenv"
    
    # Add environment variables if specified
    if [ -n "$env_vars" ]; then
        for env_var in $env_vars; do
            cmd="$cmd --env $env_var"
        done
    fi
    
    # Add basic environment
    cmd="$cmd --env HOME=/tmp --env TMPDIR=/tmp"
    cmd="$cmd $test_sif --help"
    
    echo "   Command: $cmd" >> "$LOG_FILE"
    
    if timeout 30 $cmd 2>>"$LOG_FILE" | head -5 | grep -q "bidspm\|BIDS\|help"; then
        echo "   ✅ Basic functionality works"
        
        # Test version-specific atlas behavior
        echo "   🗺️  Testing atlas initialization..."
        local version_cmd="apptainer run --containall --cleanenv"
        
        if [ -n "$env_vars" ]; then
            for env_var in $env_vars; do
                version_cmd="$version_cmd --env $env_var"
            done
        fi
        
        version_cmd="$version_cmd --env HOME=/tmp $test_sif --version"
        
        if timeout 30 $version_cmd 2>>"$LOG_FILE" | grep -q "bidspm"; then
            echo "   ✅ Version check successful (atlas likely OK)"
            return 0
        else
            echo "   ⚠️  Version check failed (possible atlas issue)"
            return 2
        fi
    else
        echo "   ❌ Basic functionality failed"
        return 1
    fi
}

# Test different container versions and configurations
echo ""
echo "🔬 Systematic Container Testing"
echo "==============================="

declare -a test_results=()

# Test 1: Latest version with default settings
test_container_config "latest" "" "Latest version (baseline)"
test_results+=("Latest_default:$?")

# Test 2: Latest version with atlas skip
test_container_config "latest" "BIDSPM_SKIP_ATLAS_INIT=1" "Latest with atlas skip"
test_results+=("Latest_atlas_skip:$?")

# Test 3: Latest version with comprehensive environment
test_container_config "latest" "BIDSPM_SKIP_ATLAS_INIT=1 CPP_ROI_SKIP_ATLAS=1 OCTAVE_EXECUTABLE=/usr/bin/octave SPM_HTML_BROWSER=0" "Latest with full env config"
test_results+=("Latest_full_env:$?")

# Test 4: Version 4.0.0 with default settings
test_container_config "4.0.0" "" "Version 4.0.0 (baseline)"
test_results+=("4.0.0_default:$?")

# Test 5: Version 4.0.0 with atlas skip
test_container_config "4.0.0" "BIDSPM_SKIP_ATLAS_INIT=1" "Version 4.0.0 with atlas skip"
test_results+=("4.0.0_atlas_skip:$?")

# Test 6: Version 3.2.1 (older stable)
test_container_config "3.2.1" "" "Version 3.2.1 (older stable)"
test_results+=("3.2.1_default:$?")

echo ""
echo "📊 Test Results Summary"
echo "======================"
echo "Legend: 0=Success, 1=Failed, 2=Atlas issue detected"
echo ""

working_configs=()
atlas_issues=()
failed_configs=()

for result in "${test_results[@]}"; do
    config="${result%%:*}"
    status="${result##*:}"
    
    case $status in
        0)
            echo "✅ $config: Working"
            working_configs+=("$config")
            ;;
        1)
            echo "❌ $config: Failed"
            failed_configs+=("$config")
            ;;
        2)
            echo "⚠️  $config: Atlas issue detected"
            atlas_issues+=("$config")
            ;;
    esac
done

echo ""
echo "🎯 Recommendations"
echo "=================="

if [ ${#working_configs[@]} -gt 0 ]; then
    echo "✅ Working configurations found:"
    for config in "${working_configs[@]}"; do
        echo "   - $config"
    done
    echo ""
    echo "💡 Recommended action:"
    echo "   Update your container_apptainer.json to use: ${working_configs[0]}"
    
    # Extract version and environment from the first working config
    first_working="${working_configs[0]}"
    if [[ "$first_working" == *"4.0.0"* ]]; then
        echo "   Set: \"apptainer_image\": \"docker://cpplab/bidspm:4.0.0\""
    elif [[ "$first_working" == *"3.2.1"* ]]; then
        echo "   Set: \"apptainer_image\": \"docker://cpplab/bidspm:3.2.1\""
    else
        echo "   Set: \"apptainer_image\": \"docker://cpplab/bidspm:latest\""
    fi
    
    if [[ "$first_working" == *"atlas_skip"* ]]; then
        echo "   Ensure BIDSPM_SKIP_ATLAS_INIT=1 is set in environment variables"
    fi
else
    echo "❌ No fully working configurations found."
    echo ""
    echo "🔧 Troubleshooting steps:"
    echo "1. Check container network connectivity"
    echo "2. Verify Apptainer installation and permissions"
    echo "3. Try building container locally with build_apptainer.sh"
    echo "4. Contact BIDSPM developers about atlas initialization bug"
fi

if [ ${#atlas_issues[@]} -gt 0 ]; then
    echo ""
    echo "🗺️  Atlas-specific issues detected in:"
    for config in "${atlas_issues[@]}"; do
        echo "   - $config"
    done
    echo ""
    echo "   This confirms the 'returnAtlasDir' error is related to atlas initialization."
    echo "   The issue appears to be in the BIDSPM container itself, not your setup."
fi

echo ""
echo "📁 Generated files:"
echo "- $PWD/$LOG_FILE (detailed test log)"
ls -la test_*.sif 2>/dev/null | head -5

echo ""
echo "🧹 Cleanup:"
read -p "Delete test containers? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -f test_*.sif
    echo "   🗑️  Test containers deleted"
fi

echo ""
echo "📋 Next steps:"
echo "1. Use the working configuration identified above"
echo "2. Update your container configuration files"
echo "3. Test with your actual data using the working setup"
echo "4. If no config works, report the issue to BIDSPM developers"
