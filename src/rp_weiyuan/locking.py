"""Side-of-fringe lock: refresh the mode reference before each recapture.

No laser object or serial-current centering belongs in this composition.
RP FPGA runs PI feedback; this worker only supervises/re-arms it at low rate.
"""

from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import threading
import time

from a221_workbench.instruments.redpitaya.feedback import validate_handoff
from a221_workbench.instruments.redpitaya.device import InstrumentBusy


@dataclass(frozen=True)
class LockSettings:
    fraction: float = .25
    p: float = .01
    i: float = -100.
    ival: float = 1.
    min_voltage: float = -1.
    max_voltage: float = 1.
    duration_s: float = .067108864
    loss_hold_s: float = .3
    stable_hold_s: float = .3
    capture_timeout_s: float = 5.
    retry_interval_s: float = 1.
    poll_interval_s: float = .1
    baseline_tolerance: float = .1
    target_tolerance_v: float = .02
    min_contrast_v: float = .01

    @classmethod
    def parse(cls, values):
        result = cls(**values)
        bounds = {'fraction': (.01, .99), 'duration_s': (.001, 2),
                  'loss_hold_s': (.1, 10), 'stable_hold_s': (.1, 10),
                  'capture_timeout_s': (1, 60), 'retry_interval_s': (.2, 60),
                  'poll_interval_s': (.05, 1), 'baseline_tolerance': (.01, .3),
                  'target_tolerance_v': (.0005, .2), 'min_contrast_v': (.001, 1)}
        for key, (lo, hi) in bounds.items():
            value = getattr(result, key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f'{key} 必须在 {lo}–{hi} 范围内')
        if result.capture_timeout_s <= result.stable_hold_s:
            raise ValueError('捕获等待必须长于稳定确认时间')
        if result.loss_hold_s < result.poll_interval_s or result.stable_hold_s < result.poll_interval_s:
            raise ValueError('判定时间不能短于检查间隔')
        result.handoff(0)
        return result

    def handoff(self, target):
        return validate_handoff(dict(setpoint=target, p=self.p, i=self.i, ival=self.ival,
                                     min_voltage=self.min_voltage, max_voltage=self.max_voltage))


def reference_from_capture(capture, settings):
    import numpy as np
    from a221_workbench.tasks.analysis.lock_trace import analyze_apparent_width
    payload = capture['bridge_result']
    if payload.get('input1') != 'in1' or payload.get('input2') != 'out2':
        raise ValueError('参考帧必须是 IN1 透射与 OUT2 扫描电压')
    trace = payload['trace']
    arrays = [np.asarray(trace[k], dtype=float) for k in ('t', 'ch1', 'ch2')]
    if not all(a.size >= 32 and np.isfinite(a).all() for a in arrays):
        raise ValueError('参考帧不完整或含无效采样')
    analysis = analyze_apparent_width(*arrays, settings.fraction)
    if not analysis.get('ok'):
        raise ValueError('没有找到完整的共振凹陷，请先恢复扫频并选好模式：' + str(analysis.get('error')))
    chosen = analysis['chosen']
    baseline = float(analysis['transmission_max_p95'])
    bottom = float(chosen['min_transmission'])
    contrast = baseline - bottom
    # Estimate the broadband noise on the off-resonance platform, excluding edges.
    y = arrays[1]
    platform = y >= baseline - .15 * contrast
    dy = np.diff(y)[platform[:-1] & platform[1:]]
    noise = float(np.median(np.abs(dy - np.median(dy))) / .954) if dy.size > 8 else 0.
    if contrast < max(settings.min_contrast_v, 8 * noise) or chosen['samples_below'] < 4:
        raise ValueError('共振深度或采样点不足，不能可靠建立锁定参考')
    if sum(c['samples_below'] >= 4 for c in analysis['candidates']) > 1:
        raise ValueError('扫描窗口内有多个完整凹陷，请减小扫幅，选出一个目标模式')
    if np.max(np.abs(y)) >= .995:
        raise ValueError('IN1 接近 ADC 量程边界，请先调整输入增益')
    target = bottom + settings.fraction * contrast
    tolerance = min(settings.target_tolerance_v, .2 * (baseline - target), .2 * (target - bottom))
    if tolerance < 3 * noise:
        raise ValueError('所选锁定位置与噪声相比太接近边界，请调整比例或信号质量')
    low, high = chosen['lower_side_sweep_voltage'], chosen['higher_side_sweep_voltage']
    if not settings.min_voltage < low < high < settings.max_voltage:
        raise ValueError('模式不在反馈电压范围内；请调整工作点或输出限幅')
    # Initial ival must start on the selected capture side; no hidden centering.
    if (settings.i < 0 and settings.ival < high) or (settings.i > 0 and settings.ival > low):
        raise ValueError('初始 ival 不在积分增益对应的捕获侧，请检查反馈极性和起始电压')
    return {'baseline_v': baseline, 'minimum_v': bottom, 'target_v': target,
            'fraction': settings.fraction, 'contrast_v': contrast, 'noise_v': noise,
            'target_tolerance_v': tolerance,
            'loss_threshold_v': baseline - settings.baseline_tolerance * (baseline - target),
            'mode_out2_v': float(chosen['min_sweep_voltage']),
            'crossings_out2_v': [float(low), float(high)],
            'captured_at': capture['captured_at']}


class LockDetector:
    """Pure, clock-driven decisions. A missing sample never proves loss of lock."""
    def __init__(self, settings, reference):
        self.settings, self.reference = settings, reference
        self.bad_since = self.good_since = self.last_sample = None

    def reset(self):
        self.bad_since = self.good_since = self.last_sample = None

    def sample(self, row, now):
        s, r = self.settings, self.reference
        if self.last_sample is not None and now - self.last_sample > max(.5, 3 * s.poll_interval_s):
            self.reset()
        self.last_sample = now
        v, output = row['in1_v'], row['out2_v']
        saturated = output <= s.min_voltage + .015 or output >= s.max_voltage - .015
        error = abs(v - r['target_v'])
        near_baseline = v >= r['loss_threshold_v']
        # A sustained error also catches dark input/drift and actuator saturation.
        bad = near_baseline or saturated or error > max(3 * r['target_tolerance_v'], .15 * r['contrast_v'])
        good = not saturated and error <= r['target_tolerance_v']
        self.bad_since = (now if self.bad_since is None else self.bad_since) if bad else None
        self.good_since = (now if self.good_since is None else self.good_since) if good else None
        reason = '回到非共振基线' if near_baseline else '反馈输出到达限幅' if saturated else '偏离锁定目标'
        return {'lost': self.bad_since is not None and now - self.bad_since >= s.loss_hold_s,
                'stable': self.good_since is not None and now - self.good_since >= s.stable_hold_s,
                'reason': reason}


class LockController:
    def __init__(self, rp, live, defaults=None):
        self.rp, self.live = rp, live
        self.observation = None
        self.defaults = asdict(LockSettings.parse(defaults or {}))
        self._mutex = threading.RLock()
        self._commands = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._status = dict(state='idle', active=False, epoch=0, attempts=0, feedback_used=False,
                            message='尚未锁定', reference=None, telemetry=None, updated_at=time.time())

    def status(self):
        with self._mutex:
            return deepcopy(self._status)

    def _update(self, **changes):
        with self._mutex:
            if 'state' in changes and changes['state'] != self._status['state']:
                self._status['epoch'] += 1
            self._status.update(changes, updated_at=time.time())

    def gate(self):
        state = self.status()
        return {'ready': state['state'] in ('idle', 'stopped', 'sweeping', 'locked'),
                'epoch': state['epoch'], 'state': state['state'], 'reference': state['reference']}

    def start(self, values):
        settings = LockSettings.parse({**self.defaults, **values})
        if not self._commands.acquire(False):
            raise RuntimeError('锁定操作尚未完成')
        try:
            if self.status()['active']:
                raise RuntimeError('守护已运行；如需更改参数，请先恢复扫频')
            if not self.rp.connected:
                raise RuntimeError('请先连接 RP')
            if not self.rp.bridge_status.get('supports_feedback'):
                raise RuntimeError('当前 RP 后台需更新后才能使用独立锁定守护')
            self._stop = threading.Event()
            self._update(state='preparing', active=True, attempts=0, reference=None,
                         telemetry=None, error=None, settings=asdict(settings), message='采集当前模式参考')
            self._thread = threading.Thread(target=self._run, args=(settings,), daemon=True)
            self._thread.start()
            return self.status()
        finally:
            self._commands.release()

    def _reference_capture(self, settings, sweep=None):
        """Take one fresh sweep while the measurement gate is closed.

        A live frame may still be completing when loss is detected. Wait for
        its operation guard instead of cancelling or terminating its stream.
        """
        deadline = time.monotonic() + 35
        while not self._stop.is_set():
            try:
                with self.rp.operation():
                    if self._stop.is_set():
                        return None
                    if sweep is None:
                        current = self.rp.feedback.state()
                        if current['sweep_output'] != 'out2' or current['output'] != 'off':
                            raise ValueError('请先点击恢复扫频，观察并选好完整模式后再锁定')
                        # Preserve the actual scan used to select the mode,
                        # including offset; do not substitute UI defaults.
                        sweep = {key: self.rp.asg.read(key) for key in
                                 ('waveform', 'frequency', 'amplitude', 'offset', 'trigger_source')}
                    else:
                        self.rp.feedback.off()
                        self.rp.asg.configure(**sweep)
                        if self._stop.is_set():
                            return None
                        self.rp.asg.configure(output_direct='out2')
                    if self._stop.is_set():
                        return None
                    capture = self.rp.scope.acquire(settings={'input1': 'in1', 'input2': 'out2',
                        'duration': settings.duration_s, 'trigger_source': 'asg0', 'trigger_delay': 0,
                        'rolling_mode': False}, timeout_s=5).as_dict()
                    return capture, sweep
            except InstrumentBusy:
                if time.monotonic() >= deadline:
                    raise RuntimeError('等待采集资源超时，未重新获取锁点')
                self._stop.wait(.05)
        return None

    def _run(self, settings):
        changed_output = False
        try:
            self.live.stop_and_wait()
            if self.observation:
                self.observation.suspend()
            if self._stop.is_set():
                return
            result = self._reference_capture(settings)
            if result is None or self._stop.is_set():
                return
            capture, sweep = result
            reference = reference_from_capture(capture, settings)
            detector = LockDetector(settings, reference)
            self._update(reference=reference)
            retry_at, capture_deadline = time.monotonic(), 0
            acquiring = True
            while not self._stop.is_set():
                now = time.monotonic()
                if acquiring and now >= retry_at:
                    if changed_output:
                        reference = None
                        self._update(state='relocking', reference=None, telemetry=None,
                                     message='重新扫描当前模式，获取新锁点')
                        result = self._reference_capture(settings, sweep)
                        if result is None or self._stop.is_set():
                            return
                        capture, _ = result
                        try:
                            reference = reference_from_capture(capture, settings)
                        except ValueError as exc:
                            self.rp.feedback.off()
                            self._update(state='lost', reference=None, error=str(exc),
                                         message='未取得有效新锁点，等待重新扫描：' + str(exc))
                            retry_at = time.monotonic() + settings.retry_interval_s
                            continue
                        detector = LockDetector(settings, reference)
                        self._update(reference=reference, error=None)
                    self._update(state='capturing' if not changed_output else 'relocking',
                                 message='按新锁点从初始 ival 捕获模式')
                    # stop() waits for this worker before enabling the sweep. It
                    # cannot leave a late re-arm running after restore returns.
                    if self._stop.is_set():
                        return
                    changed_output = True
                    self._update(feedback_used=True)
                    row = self.rp.feedback.handoff(**settings.handoff(reference['target_v']))
                    self._update(attempts=self.status()['attempts'] + 1, telemetry=row)
                    detector.reset()
                    capture_deadline = time.monotonic() + settings.capture_timeout_s
                    acquiring = False
                if not acquiring:
                    try:
                        row = self.rp.feedback.state()
                    except Exception as exc:
                        detector.reset()
                        # Do not send blind resets on network failure. Resume
                        # only after a fresh, valid sample has been obtained.
                        self._update(state='unknown', error=str(exc), message='监测中断；锁定状态未确认')
                        self._stop.wait(max(.5, settings.poll_interval_s))
                        continue
                    if (row['input'] != 'in1' or row['output'] != 'out2' or row['sweep_output'] != 'off'
                            or abs(row['setpoint_v'] - reference['target_v']) > .001
                            or abs(row['i'] - settings.i) > max(.01, abs(settings.i) * .01)
                            or abs(row['p'] - settings.p) > max(.001, abs(settings.p) * .01)):
                        raise RuntimeError('PID 或扫描设置被其他界面改变；已停止守护与反馈，请恢复扫频')
                    decision = detector.sample(row, time.monotonic())
                    self._update(telemetry=row, error=None)
                    state = self.status()['state']
                    if decision['stable']:
                        if state != 'locked' and self.observation:
                            self.observation.resume()
                        self._update(state='locked', message='已锁定 · IN1 守护中')
                    elif state == 'locked' and decision['lost']:
                        self._update(state='lost', reference=None,
                                     message=decision['reason'] + '，等待重新扫描获取锁点')
                        if self.observation:
                            self.observation.suspend()
                        self.rp.feedback.off()
                        acquiring, retry_at = True, time.monotonic() + settings.retry_interval_s
                    elif state != 'locked' and time.monotonic() >= capture_deadline:
                        self._update(state='lost', reference=None,
                                     message='捕获尚未确认，等待重新扫描获取锁点')
                        if self.observation:
                            self.observation.suspend()
                        self.rp.feedback.off()
                        acquiring, retry_at = True, time.monotonic() + settings.retry_interval_s
                self._stop.wait(settings.poll_interval_s)
        except Exception as exc:
            cleanup = None
            if changed_output:
                try:
                    self.rp.feedback.off()
                except Exception as off_error:
                    cleanup = str(off_error)
            self._update(state='error', active=False, error=str(exc), cleanup_error=cleanup,
                         message=str(exc) + (('; 关闭反馈未确认：' + cleanup) if cleanup else ''))

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            self.rp.stop_acquisition()
            thread.join(12)
            if thread.is_alive():
                raise RuntimeError('守护仍有未完成请求；尚未开启扫频，请稍后重试')
        # Acknowledged off also forms an ordering barrier for uncertain writes.
        if self.status()['active'] or self.status()['feedback_used']:
            self.rp.feedback.off()
        self._update(active=False, state='stopped', message='守护已停止')

    def restore(self, values):
        from .scan import restore_fine_sweep
        for name, bounds in {'frequency_hz': (1, 10000), 'amplitude_v': (.001, 1), 'duration_s': (.001, 2)}.items():
            value = values[name]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
                raise ValueError(f'{name} 必须在 {bounds[0]}–{bounds[1]} 范围内')
        with self._commands:
            self.stop()
            self.live.stop_and_wait()
            if self.observation:
                self.observation.close()
                self.observation.resume()
            try:
                restore_fine_sweep(self.rp, **values)
            except Exception as exc:
                self._update(state='error', message='恢复扫频未完成：' + str(exc))
                raise
            self._update(state='sweeping', reference=None, telemetry=None, attempts=0,
                         feedback_used=False, error=None, cleanup_error=None,
                         message='扫频中 · OUT2 扫描，IN1 观察模式')
            return self.status()
