"""Validate application snapshots and pinned environments before an atomic switch."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, data):
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


@contextmanager
def exclusive(path):
    import msvcrt
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('Close the running platform/installer before updating or launching again.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root, manifest):
    for item in manifest['files']:
        path = (root / item['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError('Missing resource: ' + item['path'])
        if sha(path) != item['sha256']:
            raise RuntimeError('Resource checksum failed: ' + item['path'])


def source_files(project):
    files = [project / 'pyproject.toml', project / 'tools/run.py', project / 'tools/probe.py']
    files += sorted(p for p in (project / 'src').rglob('*')
                    if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    return files


def source_manifest(project):
    return {'files': [{'path': p.relative_to(project).as_posix(), 'sha256': sha(p)}
                      for p in source_files(project)]}


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def environment(home, python=None):
    # Child processes must not inherit the checkout's paths or other projects' state.
    for name in ('PYTHONPATH', 'PYTHONHOME', 'MEASUREMENT_WORKBENCH_ROOT', 'A221_RUNTIME_PYTHON'):
        os.environ.pop(name, None)
    os.environ.update(PYTHONNOUSERSITE='1', A221_CONFIG_HOME=str(home / 'config'),
                      DAILY_NOTE_DATA_ROOT=str(home / 'data'), PYRPL_USER_DIR=str(home / 'pyrpl'))
    if python:
        os.environ['A221_RUNTIME_PYTHON'] = str(python)


def state_paths(state, home):
    env, release = Path(state['env']).resolve(), Path(state['release']).resolve()
    if not env.is_relative_to(home / 'envs') or not release.is_relative_to(home / 'releases'):
        raise RuntimeError('Installation state points outside this application home')
    return env / 'Scripts/python.exe', release


def checked(command, log, cwd):
    command = [str(x) for x in command]
    if command[0].lower().endswith('python.exe') and '-X' not in command:
        command[1:1] = ['-X', 'utf8']
    with log.open('a', encoding='utf-8') as output:
        output.write('Running: ' + json.dumps(command, ensure_ascii=False) + '\n'); output.flush()
        result = subprocess.run(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(f'Validation/install failed ({result.returncode}); see {log}')


def probe(state, home, config, log):
    python, release = state_paths(state, home)
    source = read(release / 'source-manifest.json')
    if fingerprint(source) != state['source']:
        raise RuntimeError('Snapshot source manifest was changed')
    verify(release, source)
    manifest = read(release / 'dependencies.json')
    if fingerprint(manifest) != state['dependencies']:
        raise RuntimeError('Snapshot dependency manifest was changed')
    environment(home, python)
    checked([python, '-I', '-X', 'utf8', release / 'tools/probe.py', release / 'dependencies.json', config], log, home)
    checked([python, '-I', '-m', 'pip', 'check'], log, home)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--mode', choices=['setup', 'launch', 'diagnose', 'repair', 'rollback'], required=True)
    args = parser.parse_args()
    project, home = args.project.resolve(), args.home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    (home / 'logs').mkdir(exist_ok=True)
    log = home / 'logs' / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + args.mode + '.log')
    log.write_text('Bootstrap Python: ' + sys.executable + '\n', encoding='utf-8')
    config = project / 'config.json'
    if not config.exists():
        shutil.copy2(project / 'config.example.json', config)
    # Check JSON syntax now; field validation uses the actual candidate application below.
    read(config)
    dependency_root = project / 'dependencies'
    dependencies = read(dependency_root / 'manifest.json')
    verify(dependency_root, dependencies)
    dep_stamp = fingerprint(dependencies)
    current_file, previous_file = home / 'current.json', home / 'previous.json'
    environment(home)
    with exclusive(home / 'application.lock'):
        current = read(current_file) if current_file.exists() else None
        if current and current.get('product') != 'rp-weiyuan-standalone':
            raise RuntimeError('This home belongs to a different installation. Use a separate RP_WEIYUAN_HOME.')
        if args.mode == 'diagnose':
            if not current:
                raise RuntimeError('Run setup.cmd first.')
            probe(current, home, config, log)
            python, _ = state_paths(current, home)
            checked([python, '-I', '-m', 'serial.tools.list_ports', '-v'], log, home)
            print('Environment, source and Qt OK. No instruments contacted.\nReport: ' + str(log))
            return
        if args.mode == 'rollback':
            if not previous_file.exists():
                raise RuntimeError('No previous validated version is available.')
            previous = read(previous_file)
            probe(previous, home, config, log)
            save(current_file, {**previous, 'rollback': True})
            if current:
                save(previous_file, current)
            print('Previous application and matching environment restored. config.json was preserved.')
            return
        source = source_manifest(project)
        source_stamp = fingerprint(source)
        respect_rollback = current and current.get('rollback') and args.mode == 'launch'
        needs_update = not current or args.mode == 'repair' or (not respect_rollback and (
            current['source'] != source_stamp or current['dependencies'] != dep_stamp))
        if needs_update:
            release = home / 'releases' / (source_stamp[:12] + '-' + uuid.uuid4().hex[:8])
            release.mkdir(parents=True)
            for item in source['files']:
                target = release / item['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(project / item['path'], target)
            verify(release, source)
            save(release / 'source-manifest.json', source)
            save(release / 'dependencies.json', dependencies)
            if not current or args.mode == 'repair' or current['dependencies'] != dep_stamp:
                env = home / 'envs' / (dep_stamp[:12] + '-' + uuid.uuid4().hex[:8])
                env.parent.mkdir(exist_ok=True)
                print('Creating isolated Python environment: ' + str(env), flush=True)
                checked([sys.executable, '-I', '-m', 'venv', env], log, home)
                python = env / 'Scripts/python.exe'
                checked([python, '-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-index',
                         '--find-links', dependency_root / 'wheels', '-r', dependency_root / 'requirements.lock'], log, home)
            else:
                env = Path(current['env'])
                print('Reusing pinned dependencies; validating new application source.', flush=True)
            version = re.search(r'__version__ = "([^"]+)"', (release / 'src/rp_weiyuan/__init__.py').read_text(encoding='utf-8')).group(1)
            replacement = dict(product='rp-weiyuan-standalone', env=str(env), release=str(release),
                               version=version, source=source_stamp, dependencies=dep_stamp)
            probe(replacement, home, config, log)
            if current:
                save(previous_file, current)
            save(current_file, replacement)
            current = replacement
        else:
            probe(current, home, config, log)
        if args.mode != 'launch':
            print('Ready. Edit config.json, then run launch.cmd.\nLog: ' + str(log))
            return
        python, release = state_paths(current, home)
        environment(home, python)
        print('正在启动 RP*微源光子测控平台 ' + current['version'] + '；在页面中点击连接才会操作仪器。', flush=True)
        code = subprocess.call([str(python), '-I', '-X', 'utf8', str(release / 'tools/run.py'),
                                '--real', '--config', str(config), '--open-browser'], cwd=home)
        if code:
            raise RuntimeError('Platform exited with code ' + str(code))


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
