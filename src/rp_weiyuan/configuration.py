"""Portable console configuration; RF correction is confined to spectrum power."""
from __future__ import annotations

import math
import re


def configured_host(config, override=None):
    host = override or config.get('rp_host', 'RP-F0F286')
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host):
        raise ValueError('rp_host 必须是 RP 名称或 IPv4 地址')
    return host


def input_ranges(config):
    ranges = config.get('input_ranges')
    if ranges is None:
        return None
    if not isinstance(ranges, dict) or set(ranges) != {'in1', 'in2'}:
        raise ValueError('input_ranges 必须包含 in1 和 in2 两个字段')
    if any(value not in ('HV', 'LV', None) for value in ranges.values()):
        raise ValueError('IN1/IN2 量程必须为 HV、LV 或 null（待核对）')
    return dict(ranges)


def spectrum_correction(config):
    """Absent section preserves legacy installations. New bundles are explicit."""
    chain = config.get('rf_chain')
    if chain is None:
        return None
    allowed = {'input', 'bias_tee_enabled', 'bias_tee_insertion_loss_db',
               'amplifier_enabled', 'amplifier_gain_db', 'highz_correction_db', 'load_ohm'}
    if not isinstance(chain, dict) or set(chain) - allowed:
        raise ValueError('rf_chain 含未知字段或不是 JSON 对象')
    if chain.get('input', 'in2') != 'in2':
        raise ValueError('当前频谱接线固定使用 IN2；rf_chain.input 必须为 in2')
    for name in ('bias_tee_enabled', 'amplifier_enabled'):
        if type(chain.get(name)) is not bool:
            raise ValueError(f'rf_chain.{name} 必须为 true 或 false')

    def number(name, default, low, high):
        value = chain.get(name, default)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'rf_chain.{name} 必须是 {low} 至 {high} 的有限数值')
        return float(value)

    gain = number('amplifier_gain_db', 23, 0, 100)
    loss = number('bias_tee_insertion_loss_db', 0, 0, 100)
    return {'enabled': True,
            'highz_correction_db': number('highz_correction_db', 20 * math.log10(2), 0, 40),
            'external_gain_db': (gain if chain['amplifier_enabled'] else 0)
                                - (loss if chain['bias_tee_enabled'] else 0),
            'load_ohm': number('load_ohm', 50, 1, 1e6)}


def verify_correction(expected, actual):
    if not actual.get('ok'):
        raise RuntimeError('PyRPL 频谱校正读取失败')
    for name, value in expected.items():
        readback = actual.get(name)
        matches = (readback is value) if type(value) is bool else (
            type(readback) in (float, int) and math.isclose(readback, value, rel_tol=1e-9, abs_tol=1e-9))
        if not matches:
            raise RuntimeError(f'PyRPL 频谱校正与 config.json 不一致：{name}；请暂停采集后重新连接')
    return actual
