"""Pair this installed console with its managed RP UART service over CON."""
import argparse
import json
import os
from pathlib import Path

from a221_workbench.instruments.redpitaya.uart_credentials import REMOTE, validate_token
from a221_workbench.instruments.redpitaya.uart_remote import save_local_token


def pair(host, app_home, console_port=None):
    from a221_workbench.instruments.redpitaya.network_recovery import Console
    if os.environ.get('WEIYUAN_UART_TOKEN'):
        raise RuntimeError('WEIYUAN_UART_TOKEN is set; remove that explicit override before pairing')
    with Console(host, console_port) as console:
        token = console.run(REMOTE, timeout=15)['token']
    token = validate_token(token)
    target = Path(app_home) / 'config/weiyuan_rp/.runtime/uart-token'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_name('uart-token.before-pairing')
        if not backup.exists():
            backup.write_bytes(target.read_bytes())
    save_local_token(target.parent, token)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='RP-f0fb33')
    parser.add_argument('--console-port')
    parser.add_argument('--home', type=Path, required=True)
    args = parser.parse_args()
    try:
        pair(args.host, args.home, args.console_port)
        print('配对成功：已验证 RP 串口服务并同步本机凭据。凭据内容不会显示。')
        print('回到软件，展开高级连接检查，点击“验证激光器读回”。')
        print('本工具没有重启 RP 或串口服务，没有向激光器发送命令。')
        return 0
    except Exception as exc:
        print('配对失败，未改动 RP 服务：' + str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
