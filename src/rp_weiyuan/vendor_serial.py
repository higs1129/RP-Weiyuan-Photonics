"""Start/stop the raw RP tunnel used by a separately installed virtual COM driver."""

from __future__ import annotations
from .paths import configuration_dir


import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from a221_workbench.instruments.redpitaya.runtime import runtime_python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    parser.add_argument('--host', default='RP-F0F286')
    parser.add_argument('--address')
    parser.add_argument('--device', help='RP UART node; omitted uses the last successful selection')
    parser.add_argument('--port', type=int, default=4001)
    args = parser.parse_args()
    root = configuration_dir("weiyuan_rp")
    state = root / '.runtime'
    state.mkdir(exist_ok=True)
    device_file = state / 'vendor-serial-device'
    device = args.device or (device_file.read_text(encoding='utf-8').strip() if device_file.exists() else '/dev/ttyPS1')
    marker, stop = state / 'vendor-serial-active.json', state / 'vendor-serial-stop'
    if args.action == 'status':
        print(marker.read_text() if marker.exists() else 'No active tunnel marker')
        return
    if args.action == 'stop':
        stop.touch()
        for _ in range(100):
            if not marker.exists():
                print('Tunnel stopped; UART released.'); return
            time.sleep(.1)
        raise RuntimeError('Stop requested; release not yet confirmed. Check vendor-serial.log')
    if marker.exists():
        raise RuntimeError('Tunnel marker already exists; stop/check the existing tunnel first')
    stop.unlink(missing_ok=True)
    config_path = root / 'config.local.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {}
    script = root.parent / 'instruments/redpitaya/serial_tunnel.py'
    with (state / 'vendor-serial.log').open('w', encoding='utf-8') as log:
        proc = subprocess.Popen([str(runtime_python(config.get('pyrpl_python'))), '-X', 'utf8',
                                 str(script), '--host', args.host, '--state-dir', str(state),
                                 '--port', str(args.port), '--device', device] + (['--address', args.address] if args.address else []), stdout=log, stderr=log,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _ in range(150):
        if marker.exists():
            device_file.write_text(device, encoding='utf-8')
            print('TCP tunnel ready on 127.0.0.1:' + str(args.port) + ' -> ' + device); return
        if proc.poll() is not None:
            raise RuntimeError((state / 'vendor-serial.log').read_text(encoding='utf-8'))
        time.sleep(.1)
    raise RuntimeError('Tunnel startup still pending; inspect vendor-serial.log before retrying')


if __name__ == '__main__': main()
