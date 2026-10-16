"""Read-only network/CON report for a second PC; never renew DHCP or set outputs."""
import argparse
import json
from pathlib import Path
import sys
from datetime import datetime


def collect(host, port=None):
    from a221_workbench.instruments.redpitaya.network_diagnostics import collect as diagnose
    from a221_workbench.instruments.redpitaya.network_recovery import Console, SNAPSHOT
    from serial.tools import list_ports
    board, error = None, ''
    try:
        with Console(host, port) as console:
            board = console.run(SNAPSHOT)
    except Exception as exc:
        error = str(exc)
    result = diagnose(host, board, error)
    result.update(time=datetime.now().astimezone().isoformat(), python=sys.version.split()[0])
    result['console_ports'] = [{'port': p.device, 'description': p.description}
                               for p in list_ports.comports() if p.vid == 0x0403 and p.pid == 0x6015]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='RP-f0fb33')
    parser.add_argument('--console-port')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('network-report.json'))
    args = parser.parse_args()
    report = collect(args.host, args.console_port)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('\n报告已保存：' + str(args.output.resolve()))


if __name__ == '__main__':
    main()
