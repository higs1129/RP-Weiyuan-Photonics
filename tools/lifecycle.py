"""Windows launch-session ownership; browser processes stay outside the job."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
import webbrowser


class SessionOwner:
    def __init__(self, parent_pid, ready_path, lock_path, grace_s=20):
        if os.name != 'nt':
            raise RuntimeError('The session launcher requires Windows.')
        import msvcrt
        self.ready_path = Path(ready_path)
        self.closing = threading.Event()
        self.callback = None
        self.grace_s = grace_s
        self.kernel = k = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            'SetInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
            'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'GetCurrentProcess': ([], w.HANDLE),
            'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
            'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
            'CloseHandle': ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            getattr(k, name).argtypes, getattr(k, name).restype = args, result
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                        ('flags', w.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                        ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class Limits(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', ctypes.c_ulonglong * 6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        self.job = k.CreateJobObjectW(None, None)
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.job or not k.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        # No inherited job handle: an app crash closes the last handle and kills its descendants.
        if not k.AssignProcessToJobObject(self.job, k.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
        self.parent = k.OpenProcess(0x100000, False, int(parent_pid))  # SYNCHRONIZE
        if not self.parent or k.WaitForSingleObject(self.parent, 0) != 258:
            raise RuntimeError('Launch window already closed.')
        self.lock = Path(lock_path).open('a+b')
        if not self.lock.tell():
            self.lock.write(b'0'); self.lock.flush()
        self.lock.seek(0)
        msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        self.kernel.WaitForSingleObject(self.parent, 0xFFFFFFFF)
        self.closing.set()
        print('Launch closed; stopping this session and verifying RP outputs.', flush=True)
        def deadline():
            time.sleep(self.grace_s)
            print('Shutdown deadline exceeded; terminating this session. RP output-off is NOT confirmed.', flush=True)
            self.kernel.TerminateJobObject(self.job, 1)
        threading.Thread(target=deadline, daemon=True).start()
        while self.callback is None:
            time.sleep(.05)
        self.callback()

    def ready(self, url, shutdown):
        self.callback = shutdown
        if not self.closing.is_set():
            temporary = self.ready_path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'pid': os.getpid(), 'url': url}), encoding='utf-8')
            os.replace(temporary, self.ready_path)


def launch(python, release, home, config):
    """Detached app survives CMD close long enough to clean up its own job."""
    directory = home / 'sessions'
    directory.mkdir(exist_ok=True)
    stem = directory / uuid.uuid4().hex
    ready, log = stem.with_suffix('.json'), stem.with_suffix('.log')
    env = dict(os.environ, RP_WEIYUAN_LAUNCH_PARENT=str(os.getpid()),
               RP_WEIYUAN_SESSION_READY=str(ready), RP_WEIYUAN_SESSION_LOCK=str(home / 'session.lock'))
    print('关闭此 CMD 将停止本次实验和后台；关闭网页不会停止。\nSession log: ' + str(log), flush=True)
    with log.open('ab', buffering=0) as output:
        process = subprocess.Popen([str(python), '-I', '-X', 'utf8', str(release / 'tools/run.py'),
                                    '--real', '--config', str(config)], cwd=home, env=env,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    opened = False
    while process.poll() is None:
        if not opened and ready.exists():
            state = json.loads(ready.read_text(encoding='utf-8'))
            print('REAL DEVICES: ' + state['url'], flush=True)
            webbrowser.open(state['url'])  # outside the instrument job
            opened = True
        time.sleep(.2)
    return process.returncode
