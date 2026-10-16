"""Incremental offline updates with validated snapshots and recoverable package swaps."""
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


CORE = 'a221-workbench'


def core_asset(manifest):
    assets = [item for item in manifest['files']
              if re.fullmatch(r'wheels/a221_workbench-[^/]+\.whl', item['path'])]
    if len(assets) != 1:
        raise RuntimeError('Expected exactly one pinned hardware-library wheel.')
    return assets[0]


def runtime_identity(manifest):
    # Source archives, licenses, drivers and download URLs do not change a venv.
    return {'packages': manifest['packages'], 'wheels': sorted(
        (item['path'], item['sha256']) for item in manifest['files']
        if item['path'].startswith('wheels/') and item['path'].endswith('.whl'))}


def foundation_identity(manifest):
    identity = runtime_identity(manifest)
    identity['packages'] = {k: v for k, v in identity['packages'].items() if k != CORE}
    identity['wheels'] = [item for item in identity['wheels']
                          if not item[0].startswith('wheels/a221_workbench-')]
    return identity


def cached_core(home, manifest):
    asset = core_asset(manifest)
    if not re.fullmatch(r'[0-9a-f]{64}', asset['sha256']):
        raise RuntimeError('Invalid wheel checksum.')
    return home / 'wheel-cache' / asset['sha256'] / Path(asset['path']).name


def cache_core(home, manifest, dependency_root):
    target = cached_core(home, manifest)
    if not target.exists() or sha(target) != core_asset(manifest)['sha256']:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.part')
        shutil.copy2(dependency_root / core_asset(manifest)['path'], temporary)
        if sha(temporary) != core_asset(manifest)['sha256']:
            raise RuntimeError('Hardware-library wheel checksum failed.')
        os.replace(temporary, target)


def snapshot_manifest(state, home):
    _, release = state_paths(state, home)
    manifest = read(release / 'dependencies.json')
    if fingerprint(manifest) != state['dependencies']:
        raise RuntimeError('Snapshot dependency manifest was changed')
    return manifest


def install_core(state, home, log):
    manifest = snapshot_manifest(state, home)
    wheel = cached_core(home, manifest)
    if not wheel.is_file() or sha(wheel) != core_asset(manifest)['sha256']:
        raise RuntimeError('Missing verified recovery wheel; existing version preserved.')
    python, _ = state_paths(state, home)
    print('Installing only hardware library: ' + wheel.name, flush=True)
    checked([python, '-I', '-m', 'pip', 'install', '--disable-pip-version-check',
             '--no-index', '--no-deps', '--force-reinstall', wheel], log, home)


def recover_update(home, config, log):
    journal = home / 'pending-update.json'
    if not journal.exists():
        return
    pending = read(journal)
    old = pending['current']
    if pending['restore_core']:
        install_core(old, home, log)
        probe(old, home, config, log)
    target = home / 'current.json'
    if old is None:
        target.unlink(missing_ok=True)
    else:
        save(target, old)
    journal.unlink()
    print('Interrupted/failed update recovered; previous installation retained.', flush=True)


def activate(replacement, current, home, config, log, *, swap_core=False):
    # Write recovery instructions before pip changes the shared environment.
    if swap_core:
        probe(current, home, config, log)
    journal = home / 'pending-update.json'
    save(journal, dict(current=current, restore_core=swap_core))
    try:
        if swap_core:
            install_core(replacement, home, log)
        probe(replacement, home, config, log)
        save(home / 'current.json', replacement)
        journal.unlink()
    except BaseException:
        # If recovery itself fails (e.g. a locked DLL), keep the journal for retry.
        recover_update(home, config, log)
        raise


def remove_managed_child(path, parent):
    # Only delete an immediate, non-reparse child of this application's directory.
    if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
        return
    if path.resolve().parent != parent.resolve():
        raise RuntimeError('Refusing cleanup outside installation home: ' + str(path))
    # Avoid following junctions nested inside an old environment as well.
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            child = Path(root) / name
            if child.is_symlink() or getattr(child.lstat(), 'st_file_attributes', 0) & 0x400:
                return
    shutil.rmtree(path)


def cleanup(home):
    if (home / 'pending-update.json').exists():
        return
    keep = {'envs': set(), 'releases': set(), 'wheel-cache': set()}
    file = home / 'current.json'
    if not file.exists():
        return
    state = read(file)
    python, release = state_paths(state, home)
    keep['envs'].add(python.parent.parent.resolve())
    keep['releases'].add(release)
    keep['wheel-cache'].add(cached_core(home, snapshot_manifest(state, home)).parent.resolve())
    # Remove the legacy rollback pointer only after current has passed validation.
    (home / 'previous.json').unlink(missing_ok=True)
    for folder, retained in keep.items():
        parent = home / folder
        if not parent.is_dir() or parent.is_symlink() or getattr(parent.stat(), 'st_file_attributes', 0) & 0x400:
            continue
        for path in parent.iterdir():
            pattern = r'[0-9a-f]{64}' if folder == 'wheel-cache' else r'[0-9a-f]{12}-[0-9a-f]{8}'
            if path.is_dir() and re.fullmatch(pattern, path.name) and path.resolve() not in retained:
                try:
                    remove_managed_child(path, parent)
                except OSError as exc:
                    print('Old files are still in use; cleanup will retry later: ' + str(exc), flush=True)


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
    if env.parent != home / 'envs' or release.parent != home / 'releases':
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
    parser.add_argument('--mode', choices=['setup', 'launch', 'diagnose', 'repair'], required=True)
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
    dep_stamp = fingerprint(dependencies)
    current_file = home / 'current.json'
    environment(home)
    with exclusive(home / 'application.lock'):
        recover_update(home, config, log)
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
        verify(dependency_root, dependencies)
        cache_core(home, dependencies, dependency_root)
        source = source_manifest(project)
        source_stamp = fingerprint(source)
        needs_update = not current or args.mode == 'repair' or (
            current['source'] != source_stamp or current['dependencies'] != dep_stamp)
        if needs_update:
            old_manifest = snapshot_manifest(current, home) if current else None
            rebuild = not current or args.mode == 'repair' or (
                foundation_identity(old_manifest) != foundation_identity(dependencies))
            core_changed = bool(current and core_asset(old_manifest)['sha256'] != core_asset(dependencies)['sha256'])
            if core_changed and not rebuild:
                old_wheel = cached_core(home, old_manifest)
                if not old_wheel.is_file() or sha(old_wheel) != core_asset(old_manifest)['sha256']:
                    # Legacy installations did not cache old wheels. Preserve their
                    # environment once instead of making an irreversible upgrade.
                    rebuild = True
                    print('Legacy recovery wheel unavailable; creating one migration environment.', flush=True)
            release = home / 'releases' / (source_stamp[:12] + '-' + uuid.uuid4().hex[:8])
            release.mkdir(parents=True)
            for item in source['files']:
                target = release / item['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(project / item['path'], target)
            verify(release, source)
            save(release / 'source-manifest.json', source)
            save(release / 'dependencies.json', dependencies)
            if rebuild:
                env = home / 'envs' / (dep_stamp[:12] + '-' + uuid.uuid4().hex[:8])
                env.parent.mkdir(exist_ok=True)
                print('Creating isolated Python environment: ' + str(env), flush=True)
                checked([sys.executable, '-I', '-m', 'venv', env], log, home)
                python = env / 'Scripts/python.exe'
                checked([python, '-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-index',
                         '--find-links', dependency_root / 'wheels', '-r', dependency_root / 'requirements.lock'], log, home)
            else:
                env = Path(current['env'])
                print('Reusing Python/PyRPL environment; updating only changed application/library files.', flush=True)
            version = re.search(r'__version__ = "([^"]+)"', (release / 'src/rp_weiyuan/__init__.py').read_text(encoding='utf-8')).group(1)
            replacement = dict(product='rp-weiyuan-standalone', env=str(env), release=str(release),
                               version=version, source=source_stamp, dependencies=dep_stamp)
            activate(replacement, current, home, config, log,
                     swap_core=core_changed and not rebuild)
            current = replacement
        else:
            probe(current, home, config, log)
        cleanup(home)
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
