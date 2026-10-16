"""One bounded latest-frame stream per RP session; original frames stay local."""

from __future__ import annotations
from copy import deepcopy
import math
import threading
import time
import uuid
from a221_workbench.instruments.redpitaya.device import InstrumentBusy


def preview(capture, buckets=450):
    """Keep each channel's extrema per bucket, including narrow spectral peaks."""
    payload = capture['bridge_result']
    trace = payload['trace']
    names = ('t', 'ch1', 'ch2') if capture['kind'] == 'scope' else ('frequency_hz', 'input1_dbm_per_hz')
    n = payload['n']
    indices = {0, n - 1}
    step = max(1, math.ceil(n / buckets))
    for start in range(0, n, step):
        stop = min(n, start + step)
        for name in names[1:]:
            values = trace[name]
            indices.add(min(range(start, stop), key=values.__getitem__))
            indices.add(max(range(start, stop), key=values.__getitem__))
    indices = sorted(indices)
    reduced = {name: [trace[name][i] for i in indices] for name in names}
    reduced.update(decimation=None, reduction='bucket_min_max', original_n=n)
    return {**capture, 'preview': True, 'bridge_result': {**payload, 'trace': reduced}}


class LiveAcquisition:
    def __init__(self, rp, *, simulated=False, lease_s=5.0):
        self.rp, self.simulated, self.lease_s = rp, simulated, lease_s
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self.run_id = None
        self.latest = self.reduced = None
        self.sequence = 0
        self.error = None
        self.fps = 0.0
        self.gate = lambda: {'ready': True, 'epoch': 0, 'state': 'idle'}
        self.validate_capture = lambda capture: capture

    @property
    def busy(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, kind, settings, *, fps=8.0, timeout_s=20.0):
        if kind not in ('scope', 'spectrum'):
            raise ValueError('请选择示波器或频谱仪')
        if not math.isfinite(fps) or not 0.5 <= fps <= 15:
            raise ValueError('刷新上限须为 0.5–15 帧/秒')
        if not math.isfinite(timeout_s) or not 0 < timeout_s <= 30:
            raise ValueError('单帧超时须在 0–30 秒以内')
        if not isinstance(settings, dict):
            raise ValueError('采集设置必须是对象')
        with self._lock:
            if self.busy:
                raise RuntimeError('已有连续采集或上一帧尚未结束，请先暂停并稍后重试')
            self.run_id = uuid.uuid4().hex
            self.kind = kind
            self.latest = self.reduced = None
            self.sequence, self.error, self.fps = 0, None, 0.0
            self._stop = threading.Event()
            self._last_seen = time.monotonic()
            self._thread = threading.Thread(target=self._run, args=(deepcopy(settings), fps, timeout_s), daemon=True)
            self._thread.start()
            return self.read(self.run_id)

    def _run(self, settings, target_fps, timeout_s):
        previous = None
        configured_epoch = None
        try:
            instrument = getattr(self.rp, self.kind)
            while not self._stop.is_set():
                started = time.monotonic()
                with self._lock:
                    if started - self._last_seen > self.lease_s:
                        self._stop.set()
                        break
                if not self.gate()['ready']:
                    self._stop.wait(.1)
                    continue
                try:
                    # Release between frames so the lock worker can rescan.
                    with self.rp.operation():
                        before = self.gate()
                        if not before['ready'] or self._stop.is_set():
                            continue
                        if configured_epoch != before['epoch']:
                            # The reference scan temporarily changed scope routing.
                            instrument.configure(**settings)
                            configured_epoch = before['epoch']
                        full = instrument.acquire(timeout_s=timeout_s).as_dict()
                        after = self.gate()
                except InstrumentBusy:
                    self._stop.wait(.1)
                    continue
                if not after['ready'] or before['epoch'] != after['epoch']:
                    continue  # Includes the whole spectrum averaging interval.
                full['lock_context'] = after
                full = self.validate_capture(full)
                reduced = preview(full)
                now = time.monotonic()
                with self._lock:
                    if self._stop.is_set():
                        break  # A late frame must not change a paused picture.
                    self.latest, self.reduced = full, reduced
                    self.sequence += 1
                    self.fps = 1 / (now - previous) if previous is not None else 1 / max(now - started, .001)
                previous = now
                self._stop.wait(max(0, 1 / target_fps - (time.monotonic() - started)))
        except Exception as exc:
            with self._lock:
                self.error = str(exc)
                self._stop.set()

    def read(self, run_id, *, after=0, full=False, pause=False):
        with self._lock:
            if run_id != self.run_id or not run_id:
                raise ValueError('采集会话已变化，请重新开始；没有操作其他页面的采集')
            self._last_seen = time.monotonic()
            if pause:
                self._stop.set()
            frame = self.latest if full else self.reduced
            return {'ok': True, 'run_id': self.run_id, 'sequence': self.sequence,
                    'running': self.busy and not self._stop.is_set(),
                    'stopping': self.busy and self._stop.is_set(), 'error': self.error,
                    'acquisition_fps': self.fps, 'simulated': self.simulated,
                    'measurement_gate': self.gate(),
                    'capture': frame if full or self.sequence > after else None}

    def close(self):
        self._stop.set()

    def stop_and_wait(self):
        self.close()
        thread = self._thread
        if thread and thread.is_alive():
            self.rp.stop_acquisition()
            thread.join(8)
            if thread.is_alive():
                raise RuntimeError('上一帧尚未结束，请稍后重试')
