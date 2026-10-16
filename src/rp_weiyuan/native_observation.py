"""App-side ownership of native observation during lock reference capture."""
import threading
import uuid


class Observation:
    def __init__(self, rp):
        self.rp = rp
        self.token = None
        self.mutex = threading.RLock()

    def request(self, action, **values):
        if not self.rp.connected:
            raise RuntimeError('请先连接 RP')
        if not (self.rp.bridge_status or {}).get('native_observation_revision'):
            raise RuntimeError('后台尚不支持原生观察；停止采集、激励和守护后重新连接以更新后台')
        # The Qt owner serializes hardware access. Suspend/state/close must be
        # serviceable while a lock reference capture owns rp.operation().
        result = self.rp.client.request('/observation', json_body=dict(action=action, **values), timeout_s=10)
        if not result.get('ok'):
            raise RuntimeError(result.get('error', '原生观察操作未确认'))
        return result

    def suspend(self):
        with self.mutex:
            # Locking itself remains usable with pre-native backends.
            if not (self.rp.bridge_status or {}).get('native_observation_revision'):
                return
            if self.token is None:
                self.token = uuid.uuid4().hex
            self.request('suspend', token=self.token)

    def resume(self):
        with self.mutex:
            if self.token:
                self.request('resume', token=self.token)
                self.token = None

    def close(self):
        with self.mutex:
            if (self.rp.bridge_status or {}).get('native_observation_revision'):
                return self.request('close')
            return {'ok': True, 'kind': None}
