"""Default startup policy for this application; generic drivers stay explicit."""

from __future__ import annotations
import math
import time
from a221_workbench.instruments.weiyuan import REG_TEC_SET_DEBUG, REG_LD_SET_DEBUG, STATE_TEC, STATE_LD
from .laser_profile import INITIAL


def _enable_and_confirm(laser, register, mask, enable, label, *, timeout_s=5.0):
    """Send at most one enable command; allow delayed firmware readback."""
    if laser.read_state_value(register) & mask:
        return
    enable(True)
    deadline = time.monotonic() + timeout_s
    while True:
        state = laser.read_state_value(register)
        if state & mask:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f'{label} 开启指令已发送，但 {timeout_s:g} 秒内未确认开启；未重发')
        time.sleep(0.2)


def start_debug(laser, previous):
    stage = '准备调试模式设定值'
    try:
        if any(previous.get(key) is None for key in ('tec_enabled', 'ld_enabled')):
            raise RuntimeError('TEC/LD 状态未知，未自动启动')
        targets = {}
        for field, key, register, method in [
            ('temperature', 'tec_set_temp', REG_TEC_SET_DEBUG, laser.set_temperature_c),
            ('current', 'ld_set_current', REG_LD_SET_DEBUG, laser.set_current_ma),
        ]:
            suffix = '_c' if field == 'temperature' else '_ma'
            value = previous[key + suffix]
            value = value if math.isfinite(value) else INITIAL[field]
            targets[field] = value
            stage = '确认调试模式' + ('温度' if field == 'temperature' else '电流') + '设定'
            if not math.isclose(previous[key + '_debug' + suffix], value, rel_tol=0, abs_tol=.02):
                method(value, debug=True)
            if not math.isclose(laser.read_float(register), value, rel_tol=0, abs_tol=.02):
                raise RuntimeError('设定值读回不一致')
        stage = '进入调试模式'
        if previous['mode'] != 1:
            laser.write_mode(1)
        if laser.read_mode() != 1:
            raise RuntimeError('模式读回不一致')
        stage = '开启 TEC 温控'
        _enable_and_confirm(laser, STATE_TEC, 2, laser.set_tec_enabled, 'TEC')
        stage = '开启 LD 电流输出'
        _enable_and_confirm(laser, STATE_LD, 4, laser.set_ld_enabled, 'LD')
        stage = '确认最终状态'
        result = laser.read_status()
        if result['mode'] != 1 or not result['tec_enabled'] or not result['ld_enabled']:
            raise RuntimeError('调试模式或 TEC/LD 开关未全部确认')
        for field, key in [('temperature', 'tec_set_temp_c'), ('current', 'ld_set_current_ma')]:
            if not math.isclose(result[key], targets[field], rel_tol=0, abs_tol=.02):
                raise RuntimeError('最终设定值读回不一致')
        return result
    except Exception as exc:
        raise RuntimeError(f'自动启动中断（{stage}）：{exc}。已执行步骤可能生效，请读取状态；未自动重发写入。') from exc
