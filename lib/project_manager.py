"""
Project Manager for BIDSPM

Manages projects with persistent storage, similar to bids_apps_runner.
Each project has its own folder with:
- project.json: Project configuration and metadata
- logs/: Execution logs
- configs/: Saved configurations

This module follows the same patterns as bids_apps_runner for compatibility.
"""

import os
import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

# Default data directory
DATA_DIR = Path.home() / ".bidspm"
PROJECTS_DIR = DATA_DIR / "projects"

# Fallback locations for logs/config used only when no project is active.
# Project-scoped runs use get_project_logs_dir()/get_project_configs_dir() instead.
GLOBAL_LOG_DIR = DATA_DIR / "logs"
GLOBAL_CONFIG_DIR = DATA_DIR / "config"

# Single file tracking the last project opened, so the app can resume it
# without requiring a project id in the URL.
CURRENT_PROJECT_FILE = DATA_DIR / "current_project.json"


def ensure_dirs():
    """Ensure data directories exist."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ProjectConfig:
    """Project configuration matching bids_apps_runner structure."""
    # Common settings
    bids_folder: str = ""
    derivatives_folder: str = ""
    fmriprep_folder: str = ""
    output_folder: str = ""
    models_file: str = ""
    node_name: str = ""
    
    # Processing settings
    space: str = "MNI152NLin2009cAsym"
    fwhm: float = 6.0
    tasks: List[str] = field(default_factory=list)
    verbosity: int = 2
    
    # Container settings
    container_type: str = "docker"  # docker, apptainer
    docker_image: str = "bidspm/bidspm:latest"
    apptainer_image: str = ""
    
    # Execution options
    actions: List[str] = field(default_factory=lambda: ["smooth", "stats"])
    pilot: bool = False
    skip_validation: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectConfig":
        """Create config from dictionary, handling missing fields."""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class Project:
    """A BIDSPM project."""
    id: str
    name: str
    description: str = ""
    created: str = ""
    last_modified: str = ""
    last_run: Optional[str] = None
    last_log: Optional[str] = None
    config: ProjectConfig = field(default_factory=ProjectConfig)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created": self.created,
            "last_modified": self.last_modified,
            "last_run": self.last_run,
            "last_log": self.last_log,
            "config": self.config.to_dict()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        """Create project from dictionary."""
        config_data = data.pop("config", {})
        config = ProjectConfig.from_dict(config_data) if config_data else ProjectConfig()
        return cls(config=config, **{k: v for k, v in data.items() 
                                      if k in ["id", "name", "description", "created", 
                                               "last_modified", "last_run", "last_log"]})


class ProjectManager:
    """
    Manage BIDSPM projects.
    
    Projects are stored in ~/.bidspm/projects/<project_id>/
    Each project directory contains:
    - project.json: Project metadata and configuration
    - logs/: Execution logs
    - configs/: Saved configurations
    """
    
    def __init__(self, projects_dir: Optional[Path] = None):
        self.projects_dir = projects_dir or PROJECTS_DIR
        self.projects_dir.mkdir(parents=True, exist_ok=True)
    
    def create_project(self, name: str, description: str = "", config: Optional[Dict[str, Any]] = None) -> Project:
        """Create a new project."""
        project_id = f"proj_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        project_dir = self.projects_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (project_dir / "logs").mkdir(exist_ok=True)
        (project_dir / "configs").mkdir(exist_ok=True)
        
        now = datetime.now().isoformat()
        project = Project(
            id=project_id,
            name=name,
            description=description,
            created=now,
            last_modified=now,
            config=ProjectConfig.from_dict(config) if config else ProjectConfig()
        )
        
        self._save_project(project)
        return project
    
    def load_project(self, project_id: str) -> Optional[Project]:
        """Load a project by ID."""
        project_dir = self.projects_dir / project_id
        project_json = project_dir / "project.json"
        
        if not project_json.exists():
            return None
        
        try:
            with open(project_json, "r") as f:
                data = json.load(f)
            return Project.from_dict(data)
        except Exception as e:
            print(f"Error loading project {project_id}: {e}")
            return None
    
    def save_project(self, project: Project) -> bool:
        """Save project configuration."""
        project.last_modified = datetime.now().isoformat()
        return self._save_project(project)
    
    def _save_project(self, project: Project) -> bool:
        """Internal save method."""
        project_dir = self.projects_dir / project.id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        project_json = project_dir / "project.json"
        try:
            with open(project_json, "w") as f:
                json.dump(project.to_dict(), f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving project {project.id}: {e}")
            return False
    
    def update_project_config(self, project_id: str, config: Dict[str, Any]) -> bool:
        """Update project configuration."""
        project = self.load_project(project_id)
        if not project:
            return False
        
        project.config = ProjectConfig.from_dict(config)
        return self.save_project(project)
    
    def update_project_log(self, project_id: str, log_filename: str) -> bool:
        """Update project's last log reference."""
        project = self.load_project(project_id)
        if not project:
            return False
        
        project.last_log = log_filename
        project.last_run = datetime.now().isoformat()
        return self.save_project(project)
    
    def list_projects(self, limit: Optional[int] = None) -> List[Project]:
        """List all projects, sorted by last modified."""
        projects = []
        
        if not self.projects_dir.exists():
            return projects
        
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            
            project = self.load_project(project_dir.name)
            if project:
                projects.append(project)
        
        # Sort by last_modified, newest first
        projects.sort(key=lambda p: p.last_modified or "", reverse=True)
        
        if limit:
            projects = projects[:limit]
        
        return projects
    
    def count_projects(self) -> int:
        """Count total projects."""
        if not self.projects_dir.exists():
            return 0
        
        count = 0
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir() and (project_dir / "project.json").exists():
                count += 1
        return count
    
    def delete_project(self, project_id: str) -> bool:
        """Delete a project and all its data."""
        project_dir = self.projects_dir / project_id
        
        if not project_dir.exists():
            return False
        
        try:
            shutil.rmtree(project_dir)
            return True
        except Exception as e:
            print(f"Error deleting project {project_id}: {e}")
            return False
    
    def rename_project(self, project_id: str, new_name: str) -> bool:
        """Rename a project."""
        project = self.load_project(project_id)
        if not project:
            return False
        
        project.name = new_name
        return self.save_project(project)
    
    def duplicate_project(self, project_id: str, new_name: Optional[str] = None) -> Optional[Project]:
        """Duplicate a project."""
        original = self.load_project(project_id)
        if not original:
            return None
        
        new_project = self.create_project(
            name=new_name or f"{original.name} (Copy)",
            description=original.description
        )
        new_project.config = ProjectConfig.from_dict(original.config.to_dict())
        self.save_project(new_project)
        
        return new_project
    
    def get_current_project_id(self) -> Optional[str]:
        """Return the id of the last project opened, if any."""
        try:
            with open(CURRENT_PROJECT_FILE, "r") as f:
                return json.load(f).get("project_id")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def set_current_project_id(self, project_id: str) -> None:
        """Record the last project opened, so the app can resume it."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CURRENT_PROJECT_FILE, "w") as f:
            json.dump({"project_id": project_id}, f)

    def get_project_logs_dir(self, project_id: str) -> Path:
        """Get the logs directory for a project.

        Logs are stored under the project's configured output folder when
        available, so they live alongside the analysis outputs rather than
        under the user home directory.
        """
        project = self.load_project(project_id)
        if project and project.config.output_folder:
            return Path(project.config.output_folder) / "logs"
        return self.projects_dir / project_id / "logs"
    
    def get_project_configs_dir(self, project_id: str) -> Path:
        """Get the configs directory for a project."""
        return self.projects_dir / project_id / "configs"
    
    def import_config(self, project_id: str, config_path: Path) -> bool:
        """Import a configuration file into a project."""
        project = self.load_project(project_id)
        if not project or not config_path.exists():
            return False
        
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
            
            # Map old config format to new format
            config_mapping = {
                "WD": "output_folder",
                "BIDS_DIR": "bids_folder",
                "DERIVATIVES_DIR": "derivatives_folder",
                "FMRIPREP_DIR": "fmriprep_folder",
                "MODELS_FILE": "models_file",
                "NODE_NAME": "node_name",
                "SPACE": "space",
                "FWHM": "fwhm",
                "TASKS": "tasks",
                "VERBOSITY": "verbosity",
                "container_type": "container_type",
                "docker_image": "docker_image",
                "apptainer_image": "apptainer_image",
            }
            
            new_config = {}
            for old_key, new_key in config_mapping.items():
                if old_key in config_data:
                    new_config[new_key] = config_data[old_key]
            
            # Also accept new format keys directly
            for key in config_data:
                if key not in config_mapping and hasattr(ProjectConfig, key.lower()):
                    new_config[key.lower()] = config_data[key]
            
            project.config = ProjectConfig.from_dict(new_config)
            return self.save_project(project)
            
        except Exception as e:
            print(f"Error importing config: {e}")
            return False
    
    def export_config(self, project_id: str, format: str = "bidspm") -> Optional[Dict[str, Any]]:
        """Export project configuration in old BIDSPM format."""
        project = self.load_project(project_id)
        if not project:
            return None
        
        config = project.config
        
        if format == "bidspm":
            # Old BIDSPM config format
            return {
                "WD": config.output_folder,
                "BIDS_DIR": config.bids_folder,
                "DERIVATIVES_DIR": config.derivatives_folder,
                "FMRIPREP_DIR": config.fmriprep_folder,
                "MODELS_FILE": config.models_file,
                "NODE_NAME": config.node_name,
                "SPACE": config.space,
                "FWHM": config.fwhm,
                "TASKS": config.tasks,
                "VERBOSITY": config.verbosity,
                "container_type": config.container_type,
                "docker_image": config.docker_image,
                "apptainer_image": config.apptainer_image,
            }
        else:
            return config.to_dict()


# Global instance
project_manager = ProjectManager()
