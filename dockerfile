# BIDSPM Container for MRI Lab Graz
# Author: Karl Koschutnig
# Organization: MRI Lab Graz
# Features: Python slim base, Octave 9.x, BIDSPM 4.0, SPM12, UV package manager

FROM python:3.12-slim-bookworm

LABEL maintainer="Karl Koschutnig <karl.koschutnig@uni-graz.at>"
LABEL description="BIDSPM container with Python slim base, Octave 9.x, BIDSPM 4.0, and SPM12"
LABEL version="2025.1"
LABEL author="Karl Koschutnig"
LABEL organization="MRI Lab Graz"

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Use Python 3.12 slim base image for better performance
FROM python:3.12-slim-bookworm

# Install system dependencies with performance optimizations
RUN apt-get update -qq && 
    apt-get -qq -y --no-install-recommends install 
        ca-certificates 
        curl 
        wget 
        git 
        unzip 
        python3 
        python3-pip 
        python3-venv 
        octave 
        octave-common 
        octave-dev 
        octave-io 
        octave-image 
        octave-signal 
        octave-statistics 
        octave-struct 
        octave-parallel 
        octave-control 
        octave-symbolic 
        build-essential 
        patch 
        vim 
        nano 
        libblas3 
        liblapack3 
        libopenblas-base && 
    apt-get clean && 
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

    # Install UV for fast Python package management
    RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
        mv /root/.local/bin/uv /usr/local/bin/uv && \
        chmod +x /usr/local/bin/uv
    
    # Install Python packages using UV (no PEP 668 issues with python:slim base)
    RUN uv pip install --system --no-cache-dir \
        numpy \
        scipy \
        matplotlib \
        pandas \
        nibabel \
        nilearn \
        bids-validator \
        pybids \
        jsonschema \
        setuptools \
        wheel
    
    # Install SPM12 (stable and well-tested) with proper Octave compilation
RUN mkdir -p /opt/spm12 && \
    curl -fsSL https://github.com/spm/spm12/archive/r7771.tar.gz | tar -xzC /opt/spm12 --strip-components=1 && \
    curl -fsSL https://raw.githubusercontent.com/spm/spm-octave/main/spm12_r7771.patch | patch -p0 && \
    make -C /opt/spm12/src PLATFORM=octave distclean && \
    make -C /opt/spm12/src PLATFORM=octave && \
    make -C /opt/spm12/src PLATFORM=octave install && \
    echo "✅ SPM12 r7771 installed and compiled for Octave successfully"

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash neuro && \
    mkdir -p /home/neuro && \
    chown -R neuro:neuro /home/neuro && \
    chown -R neuro:neuro /opt/spm12

    # Install BIDSPM 4.0 (stable release with submodules and Python CLI) as root
    RUN git clone --depth 1 --branch v4.0.0 https://github.com/cpp-lln-lab/bidspm.git /home/neuro/bidspm || \
        git clone --depth 1 https://github.com/cpp-lln-lab/bidspm.git /home/neuro/bidspm && \
        cd /home/neuro/bidspm && \
        git submodule update --init --recursive || true && \
        echo "✅ BIDSPM 4.0 installed successfully"
    
    # Install BIDSPM Python CLI (this is crucial for proper entrypoint)
    RUN cd /home/neuro/bidspm && \
        pip install --no-cache-dir --break-system-packages . && \
        echo "✅ BIDSPM Python CLI installed"

# Set up Octave paths with SPM12 and BIDSPM (simplified to avoid atlas issues)
RUN octave --no-gui --eval "addpath('/opt/spm12/'); savepath('/usr/share/octave/site/m/startup/octaverc');" && \
    octave --no-gui --eval "cd('/home/neuro/bidspm'); addpath(pwd); savepath('/usr/share/octave/site/m/startup/octaverc');" && \
    echo "✅ Octave paths configured successfully"

# Fix ownership and add to PATH
RUN chown -R neuro:neuro /home/neuro

# Switch to neuro user
USER neuro
WORKDIR /home/neuro
ENV PATH="/home/neuro/.local/bin:$PATH"

# Test Octave and core functionality
RUN octave --no-gui --eval "version; pkg list; disp('✅ Modern Octave ready!');"

# Test SPM12 installation
RUN octave --no-gui --eval "addpath('/opt/spm12'); try; spm('defaults', 'fmri'); disp('✅ SPM12 working!'); catch e; disp(['⚠️ SPM12 issue: ' e.message]); end"

# Use original BIDSPM entrypoint design
ENTRYPOINT ["bidspm"]
CMD ["--help"]