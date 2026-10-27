"""Local instrument console. Real device operations require --real; connections remain explicit."""
from __future__ import annotations
from .paths import configuration_dir
from . import __version__
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
import mimetypes
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlparse
import webbrowser
from a221_workbench.instruments.redpitaya import RedPitaya
from a221_workbench.instruments.weiyuan import WeiyuanLaser, LaserWriteNotSent
from a221_workbench.instruments.redpitaya.runtime import BridgeRuntime
from a221_workbench.instruments.redpitaya.network import resolve_host
from rp_weiyuan.locking import LockController
from rp_weiyuan.connection import UartSetup
from rp_weiyuan.connection_monitor import ConnectionMonitor
from rp_weiyuan.laser_profile import LIMITS, INITIAL
from rp_weiyuan.laser_startup import start_debug
from rp_weiyuan.laser_settings import set_confirmed
from rp_weiyuan.live import LiveAcquisition
from rp_weiyuan.native_observation import Observation
from a221_workbench.tasks.redpitaya.restart_bridge import restart_bridge
from .configuration import configured_host, spectrum_correction, verify_correction, input_ranges
STATIC = Path(__file__).parent / 'static'

class Session:

    def __init__(self, *, host=None, bridge=None, config=None):
        (self.real, self.config) = (True, config or {})
        host = configured_host(self.config, host)
        self.rf_correction = spectrum_correction(self.config)
        self.input_ranges = input_ranges(self.config)
        self.rf_readback = None
        auto_bridge = bridge is None
        bridge = bridge or 'http://127.0.0.1:7870'
        self.uart_setup = UartSetup(configuration_dir('weiyuan_rp') / '.runtime', self.config)
        self.rp = RedPitaya(host, bridge_url=bridge, client=None)
        transport = self.rp.uart(service_url=self.config.get('uart_url'), token=self.uart_setup.token())
        self.laser = WeiyuanLaser(transport=transport, slave=self.config.get('slave', 1))
        self._laser_guard = threading.Lock()
        self._connection_guard = threading.Lock()
        self.connection_monitor = ConnectionMonitor()
        self.laser_connected = False
        self.laser_error = None
        self.connection_setup = {'stage': '尚未连接', 'network': None, 'uart': None}
        self.runtime = BridgeRuntime(bridge, state_dir=configuration_dir('weiyuan_rp') / '.runtime', python=self.config.get('pyrpl_python'), auto_select=auto_bridge, upgrade_idle=True)
        self.live = LiveAcquisition(self.rp, simulated=False)
        self.live.validate_capture = self.validate_capture
        self.observation = Observation(self.rp)
        self.lock = LockController(self.rp, self.live, self.config.get('lock_defaults'))
        self.lock.observation = self.observation
        self.live.gate = self.lock.gate
        self._acquisition_control = threading.RLock()

    def info(self):
        return {'ok': True, 'simulated': False, 'host': self.rp.host, 'connected': self.rp.connected, 'periodic_burst_supported': bool(self.rp.connected and (self.rp.bridge_status or {}).get('excitation_protocol', 0) >= 3), 'excitation_supported': bool(self.rp.connected and (self.rp.bridge_status or {}).get('excitation_protocol', 0) >= 2), 'lock': self.lock.status(), 'lock_defaults': self.lock.defaults, 'laser_connected': self.laser_connected, 'laser_error': self.laser_error, 'bridge_url': self.rp.client.base, 'rp_address': (self.rp.bridge_status or {}).get('bridge', {}).get('hostname') if self.rp.connected else None, 'uart_url': getattr(self.laser.transport, 'base_url', None), 'laser_limits': LIMITS, 'laser_initial': INITIAL, 'source_version': self.config.get('source_version', ''), 'connection_health': self.connection_monitor.snapshot(), 'connection_diagnostics': self.connection_setup.get('diagnostics'), 'input_ranges': self.input_ranges, 'rf_chain': self.config.get('rf_chain'), 'rf_correction_expected': self.rf_correction, 'rf_correction_readback': self.rf_readback}

    def check_rf_correction(self, *, apply=False):
        if self.rf_correction is not None:
            params = {**self.rf_correction, 'enabled': 'true'} if apply else None
            self.rf_readback = verify_correction(self.rf_correction,
                self.rp.request('/spectrum/power_correction', params))

    def validate_capture(self, capture):
        if self.input_ranges is not None:
            capture['input_ranges'] = dict(self.input_ranges)
            capture['input_range_source'] = 'user_config_not_hardware_detected'
            capture['voltage_basis'] = 'pyrpl_native_no_hv_rescaling'
        if capture['kind'] == 'spectrum' and self.rf_correction is not None:
            verify_correction(self.rf_correction,
                              capture['bridge_result'].get('display_power_correction', {}))
            capture['rf_chain'] = dict(self.config['rf_chain'])
        return capture

    def prepare_laser_transport(self, *, ensure_service=False):
        if (configuration_dir('weiyuan_rp') / '.runtime/vendor-serial-active.json').exists():
            raise RuntimeError('激光器串口已交给厂家上位机测试；请先停止虚拟串口桥接')
        service_url = self.config.get('uart_url')
        token = self.uart_setup.token()
        key = (self.rp.host, service_url, token, self.laser.transport)
        if not ensure_service and getattr(self, '_laser_transport_cache', None) == key:
            return
        if not service_url:
            if ensure_service:
                self.connection_setup['stage'] = '正在检查并准备微源串口服务'
                self.connection_setup['uart'] = self.uart_setup.run('ensure', self.rp.host)
            service_url = 'http://' + resolve_host(self.rp.host)[1] + ':8092'
        self.laser.transport = self.rp.uart(service_url=service_url, token=self.uart_setup.token())
        self._laser_transport_cache = (self.rp.host, self.config.get('uart_url'),
                                       self.uart_setup.token(), self.laser.transport)

    def connect_laser(self, *, activate=False):
        with self._laser_guard:
            try:
                self.prepare_laser_transport(ensure_service=activate or not self.laser_connected)
                self.connection_setup['stage'] = '正在读取激光器状态'
                status = self.laser.read_status()
                if activate:
                    self.connection_setup['stage'] = '通信已确认，正在执行激光器启动'
                    status = start_debug(self.laser, status)
            except Exception as exc:
                self._laser_transport_cache = None
                self.laser_connected = False
                self.laser_error = str(exc)
                self.connection_monitor.record('laser', False, str(exc))
                self.connection_setup['stage'] = '激光器通信或启动失败：' + str(exc)
                self.connection_setup['diagnostics'] = {'summary': 'RP 已连接，激光器通信或启动未完成', 'detail': str(exc), 'advice': ['使用下方“仅验证激光器读回”重试通信检查；若明确配置了 uart_token，请核对该凭据。']}
                raise
            self.laser_connected = True
            self.laser_error = None
            self.connection_setup.pop('diagnostics', None)
            self.connection_monitor.record('laser', True)
            self.connection_setup['stage'] = 'RP 与微源通信已确认'
            return {'ok': True, 'status': status, 'simulated': False}

    def set_laser(self, action, body):
        values = dict(INITIAL) if action == 'laser/initialize' else {action.split('/')[1]: float(body['value'])}
        for (field, value) in values.items():
            limits = LIMITS[field]
            if not math.isfinite(value) or not limits[0] <= value <= limits[1]:
                unit = '℃' if field == 'temperature' else 'mA'
                raise ValueError(f'允许范围为 {limits[0]:g}–{limits[1]:g} {unit}')
        with self._laser_guard:
            applied = []
            confirmed = {}
            try:
                self.prepare_laser_transport()
                for (field, value) in values.items():
                    result = set_confirmed(self.laser, field, value)
                    if confirmed and result['mode'] != confirmed['mode']:
                        raise RuntimeError('连续设置期间控制模式变化，请读取状态；未重发写入')
                    confirmed.update(result)
                    applied.append(field)
            except Exception as exc:
                self._laser_transport_cache = None
                self.laser_connected = False
                outcome = '当前项未发送。' if isinstance(exc, LaserWriteNotSent) else '失败项可能已生效，未重试。'
                self.laser_error = f'设置未全部确认；已确认 {applied}；{outcome}{exc}'
                raise RuntimeError(self.laser_error) from exc
            # set_confirmed has already verified the write echo, setpoint and mode.
            # A full status adds ten serial round trips without making the write
            # more current. Leave measured values explicitly stale until requested.
            (self.laser_connected, self.laser_error) = (True, None)
            return {'ok': True, 'status': None, 'confirmed': confirmed, 'warning': None,
                    'applied': applied, 'simulated': False}

    def _restart_backend(self, host):
        """Shared by explicit restart and every connect-and-start action.

        The caller holds _connection_guard and has prepared the RP network.
        """
        if self.live.busy or self.lock.status()['active']:
            raise RuntimeError('请先暂停采集并停止锁定守护，再重启 RP 后台')
        self.rp.connected = False
        client = self.runtime.client_for_restart(host)
        self.connection_setup['stage'] = '正在核验并退出旧后台，然后启动新 PyRPL'
        result = restart_bridge(host, bridge_url=client.base,
                                python=self.runtime.python,
                                state_dir=self.runtime.state_dir / 'restarts',
                                timeout_s=self.runtime.timeout_s,
                                _on_started=lambda process, _: setattr(self.runtime, 'process', process))
        if not result.get('ok'):
            raise RuntimeError('RP 后台重启失败（' + result.get('stage', 'unknown') + '）：'
                               + result.get('error', '') + '；日志：' + str(result.get('log_path', '未生成')))
        self.runtime.client = self.rp.client = client
        self.rp.host = host
        self.rp.connect()
        self.check_rf_correction(apply=True)
        self.connection_monitor.record('rp', True)
        self.connection_setup['stage'] = '新后台已就绪，RP 输出已确认关闭'
        return result

    def dispatch(self, action, body):
        if action.startswith('observation/'):
            command = action.split('/')[1]
            with self._acquisition_control:
                if command == 'close':
                    return self.observation.close()
                if command == 'state':
                    return self.observation.request('state')
                if not self.lock.gate()['ready']:
                    raise RuntimeError('正在锁模/重锁；完成后将恢复原生观察')
                if command == 'open':
                    self.live.stop_and_wait()
                    kind = body['kind']
                    if kind == 'spectrum':
                        self.check_rf_correction(apply=True)
                    return self.observation.request('open', kind=kind, settings=body.get('settings', {}), run=body.get('run', 'continuous'))
                if command == 'run':
                    return self.observation.request('run', run=body['run'])
                raise ValueError('Unknown native observation action')
        if action == 'excitation/plan':
            from a221_workbench.instruments.redpitaya.excitation import burst_capture_plan
            return {'ok': True, **burst_capture_plan(body['frequency'], body['cycles'])}
        if action == 'live/armed':
            state = self.live.read(body['run_id'])
            if not state['running'] or self.live.kind != 'scope':
                raise RuntimeError('同步采集未运行，尚未发送 burst')
            return self.rp.client.request('/scope/armed', timeout_s=3)
        if action.startswith('excitation/'):
            if not self.rp.connected:
                raise RuntimeError('RP 尚未连接；未发送激励控制请求')
            if not (self.rp.bridge_status or {}).get('supports_excitation') or (action == 'excitation/run' and (self.rp.bridge_status or {}).get('excitation_protocol', 0) < 2):
                raise RuntimeError('设备后台仍是旧版，未发送激励控制请求。请暂停采集、停止守护，在“仪器连接”点击“重启 RP 后台”；关闭网页或重开平台不会更新这个后台。')
        if action in ('excitation/stop', 'excitation/keepalive'):
            return self.rp.excitation.control(action.split('/')[1], body['run_id'])
        if action == 'excitation/run':
            from a221_workbench.instruments.redpitaya.excitation import validate
            settings = validate(body['settings'])
            if settings['mode'] == 'periodic_burst' and (self.rp.bridge_status or {}).get('excitation_protocol', 0) < 3:
                raise RuntimeError('当前后台不支持周期 burst；请停止采集和守护后重启 RP 后台')
            with self._acquisition_control:
                before = self.lock.gate()
                if not before['ready']:
                    raise RuntimeError('正在捕获或重锁，请等待锁定稳定后发送激励')
                if settings['observe'] and settings['mode'] == 'burst':
                    self.live.stop_and_wait()
                if body.get('native_observation'):
                    if settings['observe']:
                        raise ValueError('原生单次观察请先在 Scope 中等待触发')
                    result = self.rp.excitation.run(settings, run_id=body['run_id'], native_observation=True)
                else:
                    result = self.rp.excitation.run(settings, run_id=body['run_id'])
                if 'capture' in result:
                    after = self.lock.gate()
                    if not after['ready'] or before['epoch'] != after['epoch']:
                        raise RuntimeError('激励采集期间锁定状态变化，已丢弃本帧')
                    result['capture']['lock_context'] = after
                    result['capture'] = self.validate_capture(result['capture'])
                return result
        if action == 'live/release-wait':
            with self._acquisition_control:
                self.live.read(body['run_id'], pause=True)
                self.live.stop_and_wait()
                return {'ok': True}
        if action == 'connection/check':
            return {'ok': True, 'connection_health': self.connection_monitor.check(self)}
        if action == 'lock':
            return {'ok': True, 'lock': self.lock.start(body.get('settings', {}))}
        if action == 'fine-sweep':
            return {'ok': True, 'lock': self.lock.restore(body)}
        if action == 'live/start':
            if self.lock.status()['state'] == 'preparing':
                raise RuntimeError('正在采集锁定参考，请稍后开始观察')
            if body['kind'] == 'spectrum':
                self.check_rf_correction()
            with self._acquisition_control:
                self.observation.close()
                settings = self.observation_settings(body['kind'], body.get('settings', {}), view=body.get('view', 'time'))
                if body['kind'] == 'scope' and settings.get('trigger_source') == 'asg1' and not (self.rp.bridge_status or {}).get('scope_trigger_wait_revision'):
                    raise RuntimeError('RP 后台尚未更新触发等待修复；请暂停采集、停止激励和守护，再在仪器连接中重启 RP 后台')
                return self.live.start(body['kind'], settings, fps=float(body.get('fps', 8)), timeout_s=float(body.get('timeout_s', 20)))
        if action in ('live/latest', 'live/pause', 'live/release'):
            return self.live.read(body['run_id'], after=int(body.get('after', 0)), full=action == 'live/pause', pause=action != 'live/latest')
        if action == 'stop' and self.live.busy:
            self.live.close()
            return {'ok': True, 'stopping': True}
        if self.live.busy and (not action.startswith('laser/')):
            raise RuntimeError('连续采集占用 RP；请暂停并等待当前帧结束后修改 RP 设置')
        if self.lock.status()['active'] and action in ('asg/configure', 'pid/configure', 'connect', 'rp/restart', 'uart/deploy'):
            raise RuntimeError('锁定守护正在使用仪器；请先恢复扫频')
        if action == 'rp/restart':
            with self._connection_guard:
                host = str(body.get('host', self.rp.host)).strip()
                if not host or any(c in host for c in '/\\?#@ \r\n'):
                    raise ValueError('请填写 RP 主机名或 IP')
                if self.rp.connected and host.lower() != self.rp.host.lower():
                    raise ValueError('请重启当前会话的 RP；其他设备请新开会话')
                if self.live.busy or self.lock.status()['active']:
                    raise RuntimeError('请先暂停采集并停止锁定守护，再重启 RP 后台')
                self.rp.connected = False
                self.connection_monitor.record('rp', None)
                self.connection_setup = {'stage': '正在检查目标 RP 网络', 'network': None, 'uart': None}
                try:
                    self.connection_setup['network'] = self.uart_setup.prepare_network(host)
                    result = self._restart_backend(host)
                    return {**result, 'rp_connected': True, 'setup': self.connection_setup}
                except Exception as exc:
                    self.connection_setup['stage'] = str(exc)
                    self.connection_setup['diagnostics'] = getattr(exc, 'diagnostics', None)
                    self.connection_monitor.record('rp', False, str(exc))
                    raise
        if action == 'connect':
            with self._connection_guard:
                host = str(body.get('host', self.rp.host)).strip()
                if not host or any((c in host for c in '/\\?#@ \r\n')):
                    raise ValueError('请填写 RP 主机名或 IP')
                if host != self.rp.host:
                    if self.rp.connected:
                        raise ValueError('当前会话已连接另一台设备；请新开控制台会话，避免影响正在运行的输出')
                    self.rp.host = host
                    self.laser.transport = self.rp.uart(service_url=self.config.get('uart_url'), token=self.uart_setup.token())
                if self.runtime:
                    self.rp.connected = False
                    self.connection_monitor.record('rp', None)
                    self.connection_monitor.record('laser', None)
                    self.laser_connected = False
                    self.connection_setup = {'stage': '正在查找 RP；必要时通过 CON 恢复网络',
                                             'network': None, 'uart': None}
                try:
                    if self.runtime:
                        self.connection_setup['network'] = self.uart_setup.prepare_network(host)
                        self.connection_setup['restart'] = self._restart_backend(host)
                        result = self.rp.bridge_status
                    else:
                        result = self.rp.connect()
                        self.check_rf_correction(apply=True)
                except Exception as exc:
                    self.connection_setup['stage'] = str(exc)
                    self.connection_setup['diagnostics'] = getattr(exc, 'diagnostics', None)
                    self.connection_monitor.record('rp', False, str(exc))
                    raise
                self.connection_monitor.record('rp', True)
                try:
                    laser = self.connect_laser(activate=True)
                except Exception as exc:
                    laser = {'ok': False, 'error': str(exc)}
                return {**result, 'rp_connected': True, 'laser': laser, 'setup': self.connection_setup}
        if action == 'laser/connect':
            return self.connect_laser(activate=True)
        if action in ('uart/inspect', 'uart/deploy'):
            if False:
                raise ValueError('UART 部署只在真实设备模式使用')
            host = str(body.get('host') or self.rp.host).strip()
            if self.rp.connected and host != self.rp.host:
                raise ValueError('请使用当前已连接的 RP')
            with self._connection_guard:
                result = self.uart_setup.run(action.split('/')[1], host, device=body.get('device'))
                if action == 'uart/deploy':
                    self.rp.host = host
                    self.laser.transport = self.rp.uart(token=self.uart_setup.token())
                    self.laser_connected = False
                    self.laser_error = None
                return result
        if action in ('pyrpl/show', 'pyrpl/hide'):
            if False:
                raise ValueError('当前是模拟模式，请从真实设备入口启动后打开 PyRPL')
            if not self.rp.connected:
                with self._connection_guard:
                    self.runtime.ensure(self.rp.host)
                    self.rp.client = self.runtime.client
                    self.rp.connect()
                    self.check_rf_correction(apply=True)
            if not self.rp.bridge_status.get('supports_gui'):
                raise RuntimeError('当前 bridge 版本不支持打开窗口；需使用新版 bridge，不会启动第二个实例')
            return self.rp.request('/gui/' + action.split('/')[1])
        if action == 'laser/status':
            return self.connect_laser()
        if action in ('laser/temperature', 'laser/current', 'laser/initialize'):
            return self.set_laser(action, body)
        if action == 'stop':
            return self.rp.stop_acquisition()
        with self.rp.operation():
            if action in ('scope/acquire', 'spectrum/acquire'):
                kind = action.split('/')[0]
                if kind == 'spectrum':
                    self.check_rf_correction()
                before = self.lock.gate()
                if not before['ready']:
                    raise RuntimeError('正在捕获或锁定状态未确认，请等待锁定后采集')
                instrument = getattr(self.rp, kind)
                result = instrument.acquire(settings=self.observation_settings(kind, body.get('settings', {}), view=body.get('view', 'time')), timeout_s=body.get('timeout_s', 20))
                after = self.lock.gate()
                if not after['ready'] or before['epoch'] != after['epoch']:
                    raise RuntimeError('本帧期间锁定状态变化，已丢弃本次数据')
                return {'ok': True, 'capture': self.validate_capture({**result.as_dict(), 'lock_context': after}), 'simulated': False}
            if action in ('asg/configure', 'pid/configure'):
                instrument = getattr(self.rp, action.split('/')[0])
                return {'ok': True, 'applied': instrument.configure(**body['settings'])}
        raise ValueError('Unknown action')

    def observation_settings(self, kind, settings, *, view='time'):
        if kind == 'scope':
            settings = dict(settings)
            source = settings.pop('trigger_source', 'immediately')
            show_source = settings.pop('show_source', False)
            if source not in ('immediately', 'asg1') or not isinstance(show_source, bool):
                raise ValueError('不支持的时域触发或显示选项')
            sweep_view = view == 'initialize' and self.lock.status()['state'] in ('idle', 'stopped', 'sweeping')
            if view == 'initialize':
                from .scan import mode_scope_settings
                return {**settings, **mode_scope_settings(
                    settings.get('duration', self.lock.defaults['duration_s']), sweeping=sweep_view)}
            return {**settings, 'input1': 'asg1' if view == 'time' and show_source else 'in1', 'input2': 'asg0' if sweep_view else 'in2',
                    'trigger_source': 'asg0' if sweep_view else source if view == 'time' else 'immediately',
                    'trigger_delay': 0, 'rolling_mode': False}
        if kind == 'spectrum':
            return {**settings, 'baseband': True, 'input1_baseband': 'in2', 'input2_baseband': 'in2'}
        raise ValueError('请选择时域或频域采集')

def make_server(address, session):

    class Handler(BaseHTTPRequestHandler):

        def log_message(self, *args):
            pass

        def reply(self, code, payload):
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/api/info':
                return self.reply(200, session.info())
            if path == '/api/connection/status':
                return self.reply(200, {'ok': True, **session.connection_setup})
            if path == '/api/lock/status':
                return self.reply(200, {'ok': True, 'lock': session.lock.status()})
            file = (STATIC / (path.lstrip('/') or 'index.html')).resolve()
            if not file.is_relative_to(STATIC.resolve()) or not file.is_file():
                return self.reply(404, {'ok': False})
            data = file.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', ('text/javascript' if file.suffix == '.js' else mimetypes.guess_type(file)[0] or 'text/plain') + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.headers.get('X-Instrument-Console') != '1':
                return self.reply(403, {'ok': False, 'error': 'Missing local UI header'})
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                return self.reply(403, {'ok': False, 'error': 'Cross-origin request rejected'})
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= (524288 if self.path == '/api/excitation/run' else 16384):
                    raise ValueError('Invalid request size')
                if not self.path.startswith('/api/'):
                    raise ValueError('Unknown endpoint')
                body = json.loads(self.rfile.read(size))
                result = session.dispatch(self.path[5:], body)
                self.reply(200, result)
            except Exception as exc:
                self.reply(400, {'ok': False, 'error': str(exc)})
    return ThreadingHTTPServer(address, Handler)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', action='store_true', required=True, help='Select the real instrument console; the demo has been removed')
    parser.add_argument('--host', default=None)
    parser.add_argument('--bridge', default=None, help='固定 bridge 地址；省略时按 RP 自动选择本机后台')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    if args.config is None:
        local = configuration_dir('weiyuan_rp') / 'config.local.json'
        if local.is_file():
            args.config = local
    config = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
    config['source_version'] = __version__
    session = Session(host=args.host, bridge=args.bridge, config=config)
    server = make_server(('127.0.0.1', args.port), session)
    url = f'http://127.0.0.1:{server.server_address[1]}'
    print(f"{'REAL DEVICES'}: {url}", flush=True)
    if args.open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        session.live.close()
        try:
            if session.lock.status()['active']:
                session.lock.stop()
        finally:
            server.server_close()
            if session.rp.connected:
                try:
                    session.observation.close()
                    session.observation.resume()
                except Exception:
                    logging.exception('Closing native observation failed')
            session.laser.close()
            session.rp.close()
if __name__ == '__main__':
    main()
