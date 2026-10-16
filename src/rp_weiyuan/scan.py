"""Compositions use existing instrument objects, never create connections."""

from __future__ import annotations

import uuid
import math


def mode_scope_settings(duration_s, *, sweeping=True, reference=False):
    """Explicit lock/initialization profile, independent of native observation.

    trace_average counts complete acquisitions; average only affects hardware
    decimation. Never inherit a native viewer's 50-frame averaging request.
    Stop auto-run first, before properties that may invoke PyRPL setup().
    """
    return dict(run_continuous=False, trace_average=1, average=True,
                input1='in1', input2='out2' if reference else 'asg0' if sweeping else 'in2',
                duration=duration_s, trigger_source='asg0' if sweeping or reference else 'immediately',
                trigger_delay=0, rolling_mode=False)


def restore_fine_sweep(rp, *, frequency_hz, amplitude_v, duration_s):
    """Show IN1/ASG0 with ASG0 scope trigger; keep the OUT2 actuator route."""
    if not all(math.isfinite(v) and v > 0 for v in (frequency_hz, amplitude_v, duration_s)):
        raise ValueError('Fine sweep frequency, amplitude and duration must be positive and finite')
    with rp.operation():
        rp.stop_acquisition()
        rp.pid.configure(p=0, i=0, output_direct='off')
        rp.asg.configure(output_direct='off')
        rp.asg.configure(waveform='ramp', frequency=frequency_hz, amplitude=amplitude_v, offset=0,
                         trigger_source='immediately')
        rp.scope.configure(**mode_scope_settings(duration_s))
        rp.asg.configure(output_direct='out2')
    return {'ok': True, 'route': 'in1/asg0 -> scope; asg0 -> out2; pid0 off'}


def lock_current_mode(rp, laser, *, settings):
    """Reuse existing centering/PID algorithm, preserving caller ownership.

    Success leaves the lock running. Failure disables pid0 and asg0 output;
    laser set current is NOT automatically restored. Real-device validation pending.
    """
    from a221_workbench.workflows.locking import weiyuan_current_mode_lock as old

    args = old.build_parser().parse_args([])
    required = {'min_current_ma', 'max_current_ma', 'sweep_amplitude', 'sweep_frequency',
                'p', 'low_i', 'final_i_magnitude', 'initial_ival'}
    if required - settings.keys():
        raise ValueError(f'Explicit lock parameters required: {sorted(required - settings.keys())}')
    forbidden = {'base', 'laser_port', 'slave', 'tag', 'keep_captures', 'save_summary'}
    if set(settings) - vars(args).keys() or set(settings) & forbidden:
        raise ValueError('Unknown or connection/output parameter in lock settings')
    for key, value in settings.items():
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError(f'Non-finite lock setting: {key}')
        setattr(args, key, value)
    if type(args.max_center_iterations) is not int or not 1 <= args.max_center_iterations <= 100:
        raise ValueError('max_center_iterations must be 1..100')
    for key in ('final_monitor_seconds', 'monitor_interval', 'duration', 'sweep_frequency', 'sweep_amplitude', 'max_current_step_ma'):
        if getattr(args, key) <= 0:
            raise ValueError(f'{key} must be positive')
    if args.final_monitor_seconds > 300 or args.monitor_interval > 10:
        raise ValueError('Monitor duration/interval exceeds the bounded workflow limits')
    for key in ('settle_seconds', 'current_settle_seconds'):
        if not 0 <= getattr(args, key) <= 60:
            raise ValueError(f'{key} must be 0..60 seconds')
    if not args.min_current_ma <= args.max_current_ma:
        raise ValueError('Invalid current limits')
    args.no_initialize_current = settings.get('no_initialize_current', True)
    if not args.no_initialize_current and 'initial_current_ma' not in settings:
        raise ValueError('Explicit initial_current_ma required when initialization is enabled')
    if not args.no_initialize_current and not args.min_current_ma <= args.initial_current_ma <= args.max_current_ma:
        raise ValueError('Initial current outside limits')
    args.base, args.keep_captures, args.save_summary = rp, False, False
    args.tag = 'lock_' + uuid.uuid4().hex
    with rp.operation():
        result = {'ok': False, 'steps': []}
        try:
            result['initial_laser_status'] = laser.read_status()
            current = result['initial_laser_status']['ld_set_current_ma']
            if not args.min_current_ma <= current <= args.max_current_ma:
                raise ValueError('Present set current outside specified experiment limits')
            rp.stop_acquisition()
            rp.pid.configure(p=0, i=0, output_direct='off')
            rp.asg.configure(output_direct='off')
            final, steps = old.center_and_width(args, args.tag, laser)
            result['steps'].extend(steps)
            target = float(final['lockpoint_analysis']['transmission_lock'])
            sign, steps = old.pid_handoff(args, target)
            result['steps'].extend(steps)
            monitor = old.monitor_live(rp, args.final_monitor_seconds, args.monitor_interval, target)
            result.update(target_ch1_v=target, selected_i_sign=sign, monitor=monitor,
                          final_pid=old.sample(rp), final_laser_status=laser.read_status())
            result['ok'] = bool(monitor.get('ok') and not monitor.get('out2_saturated')
                                and not monitor.get('ival_saturated')
                                and abs(monitor.get('target_error_mean', float('inf'))) <= args.max_final_target_error_v)
            if not result['ok']:
                result['error'] = 'Final lock verification failed'
        except Exception as exc:
            result['error'] = str(exc)
        if not result['ok']:
            result['cleanup_errors'] = []
            for module, fields in [(rp.pid, {'p': 0, 'i': 0, 'output_direct': 'off'}),
                                   (rp.asg, {'output_direct': 'off'})]:
                for key, value in fields.items():
                    try:
                        module.configure(**{key: value})
                    except Exception as exc:
                        result['cleanup_errors'].append(str(exc))
        return result
