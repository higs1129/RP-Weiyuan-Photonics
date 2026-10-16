"""Confirm a setpoint independently of the slower full status snapshot."""

from __future__ import annotations
import math
from a221_workbench.instruments.weiyuan import (
    LaserWriteNotSent, REG_TEC_SET_RUN, REG_TEC_SET_DEBUG,
    REG_LD_SET_RUN, REG_LD_SET_DEBUG,
)


def set_confirmed(laser, field, value):
    try:
        mode = laser.read_mode()
        if mode not in (0, 1):
            raise ValueError(f'未知控制模式 {mode}')
    except Exception as exc:
        raise LaserWriteNotSent(f'读取控制模式失败，未发送设置：{exc}') from exc
    if field == 'temperature':
        method, registers, key = laser.set_temperature_c, (REG_TEC_SET_RUN, REG_TEC_SET_DEBUG), 'tec_set_temp_c'
    else:
        method, registers, key = laser.set_current_ma, (REG_LD_SET_RUN, REG_LD_SET_DEBUG), 'ld_set_current_ma'
    method(value, debug=mode == 1)
    actual = laser.read_float(registers[mode])
    if not math.isclose(actual, value, rel_tol=0, abs_tol=.02):
        raise RuntimeError(f'{field} 设定读回不一致：请求 {value}，读回 {actual}')
    if laser.read_mode() != mode:
        raise RuntimeError('设置期间控制模式发生变化，当前工作点未确认')
    return {'mode': mode, key: actual}
