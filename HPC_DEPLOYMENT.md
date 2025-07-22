# BIDSPM HPC Deployment Guide

## 🚀 Quick Start für HPC mit Apptainer

### 1. Container vorbereiten (einmalig)
```bash
# Container Image ziehen (wird automatisch beim ersten Lauf gemacht)
apptainer pull docker://cpplab/bidspm:latest

# Oder explizit:
apptainer pull bidspm_latest.sif docker://cpplab/bidspm:latest
```

### 2. Konfiguration für HPC
```bash
# Production config für Apptainer verwenden
python bidspm.py -s your_config.json -c container_production.json --pilot
```

### 3. Typischer HPC Workflow

#### Pilot Testing:
```bash
# Test mit einem Subjekt
python bidspm.py -s hpc_config.json -c container_production.json --pilot
```

#### Production Run:
```bash
# Alle Subjekte
python bidspm.py -s hpc_config.json -c container_production.json
```

### 4. Troubleshooting

#### Wenn Apptainer nicht automatisch erkannt wird:
```bash
python bidspm.py -s config.json -c container_apptainer.json --pilot
```

#### Container Cache Issues:
```bash
# Cache leeren falls Probleme
apptainer cache clean

# Image neu ziehen
apptainer pull --force docker://cpplab/bidspm:latest
```

#### Debugging:
```bash
# Verbosity erhöhen
# In config.json: "VERBOSITY": 3

# Container direkt testen
apptainer run docker://cpplab/bidspm:latest --help
```

## 🔧 Container-Konfigurationen

### container_production.json (für HPC):
```json
{
  "container_type": "apptainer",
  "docker_image": "", 
  "apptainer_image": "docker://cpplab/bidspm:latest"
}
```

### Für lokale .sif Datei:
```json
{
  "container_type": "apptainer",
  "docker_image": "",
  "apptainer_image": "/path/to/bidspm_latest.sif"
}
```

## 💡 HPC Best Practices

1. **Erste Tests mit Pilot-Modus**
2. **Verbosity auf 3 für Debugging**
3. **tmp-Verzeichnisse auf lokaler SSD wenn möglich**
4. **Container-Cache in User-Verzeichnis**
5. **Bei Problemen: Container neu ziehen**
