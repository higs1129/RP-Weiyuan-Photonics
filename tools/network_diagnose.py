"""Read-only network/CON report for a second PC; never renew DHCP or set outputs."""
import argparse
import json
from pathlib import Path
import sys
from datetime import datetime


def collect(host, port=None):
    from a221_workbench.instruments.redpitaya.network_discovery import discover, _serial_inventory
    result = discover(host, use_console=True, console_port=port)
    result.update(time=datetime.now().astimezone().isoformat(), python=sys.version.split()[0])
    result['console_ports'] = _serial_inventory()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    settings_path = Path(__file__).resolve().parent.parent / 'config.json'
    settings = json.loads(settings_path.read_text(encoding='utf-8-sig')) if settings_path.exists() else {}
    from rp_weiyuan.configuration import configured_host
    parser.add_argument('--host', default=configured_host(settings, None))
    parser.add_argument('--console-port', default=settings.get('rp_console_port'))
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('network-report.json'))
    args = parser.parse_args()
    report = collect(args.host, args.console_port)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('\n报告已保存：' + str(args.output.resolve()))


if __name__ == '__main__':
    main()
