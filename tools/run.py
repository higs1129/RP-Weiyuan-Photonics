"""Launch only the local application and its pinned installed hardware library."""
import importlib.metadata
import json
from pathlib import Path
import sys


def prepare():
    root = Path(__file__).resolve().parents[1]
    manifest = root / 'dependencies.json'
    if not manifest.exists():
        manifest = root / 'dependencies/manifest.json'
    expected = json.loads(manifest.read_text(encoding='utf-8'))['packages']['a221-workbench']
    import a221_workbench
    origin = Path(a221_workbench.__file__).resolve()
    installed = Path(sys.prefix).resolve() / 'Lib/site-packages'
    if not origin.is_relative_to(installed) or importlib.metadata.version('a221-workbench') != expected:
        raise RuntimeError('The hardware library must be the pinned wheel installed inside this Python environment.')
    sys.path.insert(0, str(root / 'src'))
    return root, origin


if __name__ == '__main__':
    prepare()
    from rp_weiyuan.server import main
    main()
