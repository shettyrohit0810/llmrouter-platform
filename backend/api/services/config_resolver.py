"""Makes router YAML configs portable.

Router configs reference data and checkpoints with relative paths
(`data_path.*`, `model_path.*`). The routing library joins those onto *its own*
install directory, which for a pip-installed package is site-packages -- not
this project. `os.path.join(root, "/abs/path")` ignores `root`, so rewriting
those values to absolute paths under the platform root makes the library use
the files we actually ship, in local dev, in Docker, or on a mounted volume.

`resolve_config()` writes the rewritten copy to `<root>/.resolved_configs/`
(named by a hash of its content, so it is stable and idempotent) and returns
that path. The original file is never modified.
"""

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from backend.config import BackendConfig

_PATH_SECTIONS = ("data_path", "model_path")
_CACHE_DIR_NAME = ".resolved_configs"


def platform_root() -> Path:
    return Path(BackendConfig.from_env().repo_root).resolve()


def locate_config(config_path: str) -> Path:
    """A relative config path is relative to the platform root, not the
    process's working directory (which differs between API, worker, tests)."""
    p = Path(config_path)
    return p if p.is_absolute() else platform_root() / p


def _absolutize(section: Dict[str, Any], root: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in section.items():
        if isinstance(value, str) and value and not os.path.isabs(value):
            out[key] = str(root / value)
        else:
            out[key] = value
    return out


def resolve_config(config_path: str) -> str:
    """Returns the path of an equivalent config whose data/model paths are
    absolute. If the file doesn't exist, returns `config_path` unchanged so
    the library raises its own clear FileNotFoundError."""
    source = locate_config(config_path)
    if not source.exists():
        return config_path

    root = platform_root()
    with open(source, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    for section_name in _PATH_SECTIONS:
        section = data.get(section_name)
        if isinstance(section, dict):
            data[section_name] = _absolutize(section, root)

    rendered = yaml.safe_dump(data, sort_keys=True)
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]
    cache_dir = root / _CACHE_DIR_NAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{source.stem}-{digest}.yaml"
    if not target.exists():
        # Write-then-rename so a concurrent reader never sees a partial file.
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(rendered, encoding="utf-8")
        os.replace(tmp, target)
    return str(target)


def read_save_model_path(config_path: str) -> Optional[str]:
    """The config's `model_path.save_model_path` exactly as written (relative
    paths stay relative -- this is the portable name recorded in the model
    registry, not the machine-specific absolute location)."""
    try:
        with open(locate_config(config_path), encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        value = (data.get("model_path") or {}).get("save_model_path")
        return value if isinstance(value, str) and value else None
    except (OSError, yaml.YAMLError):
        return None
