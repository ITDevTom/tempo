import logging
import signal
import time
from .config import Settings
from .db import configure_grafana_reader, connect, migrate
from .sync import sync_once
from .tempo_client import TempoClient

log = logging.getLogger(__name__)
stop = False


def _stop(*_):
    global stop
    stop = True


def main():
    settings = Settings.from_env()
    logging.basicConfig(level=getattr(logging, __import__('os').environ.get('LOG_LEVEL', 'INFO').upper()), format='%(asctime)s %(levelname)s %(name)s %(message)s')
    log.info("worker starting: interval_seconds=%s", settings.interval_seconds)
    signal.signal(signal.SIGTERM, _stop); signal.signal(signal.SIGINT, _stop)
    client = TempoClient(settings.tempo_base_url, settings.tempo_token)
    conn = connect()
    migrate(conn)
    configure_grafana_reader(conn)
    log.info("worker database startup complete")
    while not stop:
        try:
            sync_once(conn, client, settings)
        except Exception:
            log.exception('sync failed; will retry next interval')
        for _ in range(settings.interval_seconds):
            if stop: break
            time.sleep(1)
    conn.close()
    log.info("worker stopped")


if __name__ == '__main__':
    main()
