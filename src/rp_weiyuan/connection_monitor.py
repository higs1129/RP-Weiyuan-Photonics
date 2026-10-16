"""Low-rate connection observations; never prepare, restart or enable devices."""
from copy import deepcopy
from datetime import datetime
import threading
import time

from a221_workbench.instruments.transports import HttpSerialTransport
from a221_workbench.instruments.weiyuan import WeiyuanLaser


class ConnectionMonitor:
    def __init__(self):
        self._guard = threading.Lock()
        self._last_attempt = None
        self._rows = {name: {'ok': None, 'checked_at': None, 'error': '', 'deferred': ''}
                      for name in ('rp', 'laser')}

    def snapshot(self):
        return deepcopy(self._rows)

    def record(self, name, ok, error='', *, checked_at=None):
        self._rows[name] = {'ok': ok, 'checked_at': (checked_at or time.time()) if ok is not None else None,
                            'error': error, 'deferred': ''}

    def defer(self, name, reason):
        self._rows[name] = {**self._rows[name], 'deferred': reason}

    def _busy(self, session):
        if session.live.busy or session.lock.status()['active']:
            return True
        # Also defer for single-frame captures and foreground RP operations.
        # Do not hold the device guard during monitoring or make users wait on it.
        if not session.rp._guard.acquire(False):
            return True
        session.rp._guard.release()
        return False

    def _recent_rp(self, session):
        """Reuse successful measurements without issuing additional RP commands."""
        lock = session.lock.status()
        stamp = (lock.get('telemetry') or {}).get('sampled_at') if lock['state'] == 'locked' else None
        latest = session.live.latest
        if session.live.busy and latest:
            try:
                captured = datetime.fromisoformat(latest['captured_at'].replace('Z', '+00:00')).timestamp()
                stamp = max(stamp or 0, captured)
            except (ValueError, KeyError, TypeError):
                pass
        if stamp and 0 <= time.time() - stamp < 10:
            self.record('rp', True, checked_at=stamp)
        else:
            self.defer('rp', '测量中，本轮未额外查询 RP')

    def check(self, session):
        if not self._guard.acquire(False):
            return self.snapshot()
        try:
            now = time.monotonic()
            # Shared by all tabs of this console; overlapping timers cannot
            # multiply hardware traffic. Skips also count as this minute's turn.
            if self._last_attempt is not None and now - self._last_attempt < 60:
                return self.snapshot()
            self._last_attempt = now
            if not session._connection_guard.acquire(False):
                for name in self._rows:
                    self.defer(name, '正在连接或重启，本轮检查延后')
                return self.snapshot()
            try:
                if self._busy(session):
                    self._recent_rp(session)
                    self.defer('laser', '采集或锁定中，本轮串口检查延后')
                    return self.snapshot()
                if session.rp.connected:
                    # Sampler-only read: no scope, ASG or PID configuration and
                    # no connect(), whose discovery may prepare new hardware.
                    try:
                        health = session.rp.client.health(timeout_s=1, return_errors=False)
                        expected = (session.rp.bridge_status or {}).get('bridge', {})
                        actual = health.get('bridge', {})
                        if not health.get('ok') or not expected.get('pid') or any(
                            actual.get(key) != expected.get(key) for key in ('pid', 'hostname', 'rp_identity', 'started_at')
                        ):
                            raise RuntimeError('RP 后台身份已变化或无法确认，请重新连接')
                        result = session.rp.client.request('/feedback/state', timeout_s=2)
                        if not result.get('ok'):
                            raise RuntimeError(result.get('error', 'RP 未返回有效状态'))
                        self.record('rp', True)
                    except Exception as exc:
                        self.record('rp', False, str(exc))
                else:
                    self.defer('rp', '尚未建立连接，请先连接仪器')
                if self._busy(session):
                    self.defer('laser', '采集或锁定中，本轮串口检查延后')
                elif not session.laser_connected:
                    self.defer('laser', '尚未建立串口通信，请先连接仪器')
                elif not session._laser_guard.acquire(False):
                    self.defer('laser', '激光器操作中，本轮检查延后')
                else:
                    try:
                        transport = session.laser.transport
                        if not isinstance(transport, HttpSerialTransport):
                            self.defer('laser', '当前串口不支持后台检查')
                        elif (session.uart_setup.state_dir / 'vendor-serial-active.json').exists():
                            self.defer('laser', '串口已交给厂家上位机')
                        else:
                            # A single protocol read proves laser communication;
                            # /health alone proves only the forwarding service.
                            probe = WeiyuanLaser(slave=session.laser.slave, transport=HttpSerialTransport(
                                transport.base_url, token=transport.token, timeout_s=1.2))
                            if probe.read_mode() not in (0, 1):
                                raise RuntimeError('激光器返回无效模式')
                            self.record('laser', True)
                    except Exception as exc:
                        self.record('laser', False, str(exc))
                    finally:
                        session._laser_guard.release()
                return self.snapshot()
            finally:
                session._connection_guard.release()
        finally:
            self._guard.release()
