#!/bin/bash
echo "🔧 Emergency Atlas Fix for HPC Server"
echo "===================================="
echo ""
echo "This script creates a temporary workaround for the returnAtlasDir issue"
echo "Upload this to your HPC server and run it before using bidspm.py"
echo ""

# Create a patched version of the container with function copy workaround
echo "Creating emergency atlas fix container command..."

cat > atlas_emergency_fix.sh << 'EOF'
#!/bin/bash

# Function to copy atlas functions to tmp and modify path
create_atlas_workaround() {
    echo "🔧 Creating atlas function workaround..."
    
    # Create tmp atlas directory
    mkdir -p /tmp/atlas_backup
    
    # Copy critical atlas functions to tmp
    if [ -f "/home/neuro/bidspm/lib/CPP_ROI/atlas/returnAtlasDir.m" ]; then
        cp /home/neuro/bidspm/lib/CPP_ROI/atlas/returnAtlasDir.m /tmp/atlas_backup/
        echo "✅ Copied returnAtlasDir.m to /tmp/atlas_backup/"
    fi
    
    # Copy other potentially needed atlas functions
    if [ -d "/home/neuro/bidspm/lib/CPP_ROI/atlas/" ]; then
        cp /home/neuro/bidspm/lib/CPP_ROI/atlas/*.m /tmp/atlas_backup/ 2>/dev/null
        echo "✅ Copied all atlas .m files to /tmp/atlas_backup/"
    fi
    
    # Create Octave init file to force path
    cat > /tmp/octave_init.m << 'OCTAVE_EOF'
% Emergency Atlas Path Fix
addpath('/tmp/atlas_backup');
addpath('/home/neuro/bidspm/lib/CPP_ROI/atlas');
addpath('/home/neuro/bidspm/lib/CPP_ROI');
addpath('/home/neuro/bidspm');
fprintf('🔧 Emergency atlas paths added\n');
OCTAVE_EOF
    
    echo "✅ Created emergency Octave init file"
}

# Test the workaround
test_atlas_workaround() {
    echo "🧪 Testing atlas workaround..."
    
    octave --eval "
        % Source the init file
        if exist('/tmp/octave_init.m', 'file')
            run('/tmp/octave_init.m');
        end
        
        % Test if function is now available
        if exist('returnAtlasDir', 'file')
            fprintf('✅ returnAtlasDir is now available\n');
            try
                result = returnAtlasDir();
                fprintf('🎉 SUCCESS: returnAtlasDir() returned: %s\n', result);
            catch e
                fprintf('⚠️  Function found but execution failed: %s\n', e.message);
            end
        else
            fprintf('❌ returnAtlasDir still not found\n');
        end
    "
}

# Main execution
echo "Starting emergency atlas fix..."
create_atlas_workaround
test_atlas_workaround
echo "Emergency fix complete. You can now try running bidspm.py"
EOF

chmod +x atlas_emergency_fix.sh

echo "📦 Created atlas_emergency_fix.sh"
echo ""
echo "Instructions for HPC server:"
echo "1. Upload atlas_emergency_fix.sh to your server"
echo "2. Run: apptainer exec your_container.sif bash atlas_emergency_fix.sh"
echo "3. Then try your bidspm analysis again"
echo ""
echo "This workaround copies the atlas functions to /tmp where Octave can definitely find them"
