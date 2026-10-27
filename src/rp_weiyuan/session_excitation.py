"""Keep explicit excitation alive for the launch session, independent of browser tabs."""
import logging
import threading


class SessionExcitation:
    def __init__(self, rp):
        self.rp = rp
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._run = None
        threading.Thread(target=self._renew, daemon=True).start()

    def remember(self, result, settings):
        with self._lock:
            if result.get('active') and not self._done.is_set():
                self._run = {'run_id': result['run_id'], 'settings': dict(settings)}

    def forget(self, token):
        with self._lock:
            if self._run and self._run['run_id'] == token:
                self._run = None

    def state(self):
        with self._lock:
            return dict(self._run) if self._run else None

    def close(self):
        self._done.set()

    def _renew(self):
        while not self._done.wait(2):
            run = self.state()
            if not run:
                continue
            try:
                state = self.rp.excitation.control('keepalive', run['run_id'])
                if not state.get('active'):
                    self.forget(run['run_id'])
            except Exception:
                self.forget(run['run_id'])
                logging.exception('Excitation lease lost; backend expiry remains enabled')
