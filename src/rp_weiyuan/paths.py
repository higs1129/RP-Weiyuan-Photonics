"""Application-owned local settings; never locate the workbench checkout."""
import os
from pathlib import Path

def configuration_dir(name):
    root = os.environ.get("A221_CONFIG_HOME")
    if not root:
        raise RuntimeError("Start this application with launch.cmd to select its isolated environment")
    return Path(root) / name
