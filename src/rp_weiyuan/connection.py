"""Console-side UART setup; hardware-specific deployment lives in the RP package."""

from __future__ import annotations
from importlib.util import find_spec
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

from a221_workbench.instruments.redpitaya.runtime import resolve_host, runtime_python


class ConnectionSetupError(RuntimeError):
    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics


class UartSetup:
    def __init__(self, state_dir, config):
        self.state_dir, self.config = Path(state_dir), config

    def token(self):
        explicit = os.environ.get('WEIYUAN_UART_TOKEN') or self.config.get('uart_token')
        if explicit:
            return explicit
        path = self.state_dir / 'uart-token'
        if path.exists():
            return path.read_text(encoding='utf-8').strip()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('x', encoding='utf-8') as stream:
                stream.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        return path.read_text(encoding='utf-8').strip()

    def prepare_network(self, host):
        python = runtime_python(self.config.get('pyrpl_python'))
        command = [str(python), '-X', 'utf8', '-m',
                   'a221_workbench.instruments.redpitaya.network_recovery', '--host', host]
        if self.config.get('rp_console_port'):
            command += ['--console-port', self.config['rp_console_port']]
        return self._execute(command, timeout=180)

    @staticmethod
    def _execute(command, *, timeout):
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=timeout,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            payload = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError('RP 连接准备工具失败；请检查运行环境和相关依赖') from exc
        if result.returncode or not payload.get('ok'):
            raise ConnectionSetupError(payload.get('error', 'RP connection setup failed'), payload.get('diagnostics'))
        return payload

    def run(self, action, host, *, device=None):
        _, address = resolve_host(host)
        python = runtime_python(self.config.get('pyrpl_python'))
        token = self.token()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', prefix='uart-',
                                         dir=self.state_dir, encoding='utf-8', delete=False) as stream:
            settings = Path(stream.name)
            json.dump({**self.config, 'uart_token': token, 'expected_host': host,
                       'sync_existing_token': not bool(os.environ.get('WEIYUAN_UART_TOKEN') or self.config.get('uart_token')),
                       'uart_device': device or self.config.get('uart_device')}, stream)
        script = find_spec("a221_workbench.instruments.redpitaya.uart_remote").origin
        try:
            return self._execute([str(python), '-X', 'utf8', str(script), action,
                                  '--host', address, '--settings', str(settings)], timeout=60)
        finally:
            settings.unlink(missing_ok=True)
