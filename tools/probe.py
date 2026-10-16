"""Offline validation: no instrument instances or device connections."""
import faulthandler
import importlib
import importlib.util
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import struct
import sys

faulthandler.enable()
faulthandler.dump_traceback_later(60, exit=True)
# -I removes the script directory; load only our sibling runner explicitly.
spec = importlib.util.spec_from_file_location('platform_runner', Path(__file__).with_name('run.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
root, origin = runner.prepare()
assert sys.version_info[:2] == (3, 10) and struct.calcsize('P') == 8, 'Python 3.10 x64 required'
manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
versions = {}
for name, expected in manifest['packages'].items():
    actual = metadata.version(name)
    assert actual == expected, f'{name}: expected {expected}, got {actual}'
    versions[name] = actual
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_LOGGING_TO_CONSOLE'] = '1'
from a221_workbench.instruments.redpitaya.qt_runtime import prepare_qt_plugins
prepare_qt_plugins()
for name in ('numpy', 'scipy', 'matplotlib', 'paramiko', 'serial', 'psutil', 'pyvisa',
             'pyrpl', 'qasync', 'pyqtgraph', 'rp_weiyuan.server',
             'a221_workbench.instruments.redpitaya.pyrpl_backend'):
    print('Importing ' + name, flush=True)
    importlib.import_module(name)
from rp_weiyuan.configuration import configured_host, spectrum_correction, input_ranges
config = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig'))
configured_host(config)
spectrum_correction(config)
input_ranges(config)
if config.get('pyrpl_python'):
    raise ValueError('Keep pyrpl_python null: launch.cmd selects the isolated environment.')
from qtpy.QtWidgets import QApplication, QWidget
app = QApplication.instance() or QApplication([])
widget = QWidget()
widget.resize(100, 50)
assert not widget.grab().isNull(), 'Qt rendering failed'
widget.close()
from rp_weiyuan.server import STATIC
assert (STATIC / 'brand/iop-apc.png').is_file()
import a221_workbench.instruments.redpitaya as rp
assert Path(rp.__file__).with_name('console_startup.yml').is_file()
print(json.dumps({'ok': True, 'application_source': str(root), 'hardware_library': str(origin),
                  'python': sys.executable, 'packages': versions}))
faulthandler.cancel_dump_traceback_later()
