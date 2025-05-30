#-*- coding: utf-8 -*-

import select
import pyfanotify as fan

from typing import Any
from lib import *


class FanotifyChangesWatcher(ChangesWatcher):
    """Uses fanotify to watch for changes"""

    def __init__(self, fs2es_indexer: Fs2EsIndexer):
        super().__init__(fs2es_indexer)
        self.fanotity = None
        self.fanotify_client = None
        self.poller = None

    def start(self) -> bool:
        """ Starts the changes watcher """
        self.fanotity = fan.Fanotify(init_fid=True)

        # See https://man7.org/linux/man-pages/man2/fanotify_mark.2.html
        event_types = (fan.FAN_CREATE | fan.FAN_DELETE | fan.FAN_DELETE_SELF | fan.FAN_RENAME | fan.FAN_ONDIR)

        for directory in self.directories:
            self.fanotity.mark(
                directory,
                is_type='fs',
                ev_types=event_types
            )

        self.fanotity.start()

        self.fanotify_client = fan.FanotifyClient(self.fanotity, path_pattern='*')
        self.poller = select.poll()
        self.poller.register(self.fanotify_client.sock.fileno(), select.POLLIN)

    def watch(self, timeout: float):
        """ Watches for changes via fanotify until the timeout is reached. """

        stop_at = time.time() + timeout
        self.print('Monitoring changes via fanotify until next indexing run in %s.' % daemon_wait_time)

        try:
            while self.poller.poll():
                for event in self.fanotify_client.get_events():
                    if fan.FAN_CREATE & event.ev_types:
                        self.fs2es_indexer.import_path(event.path[0].decode('utf-8'))
                    elif fan.FAN_DELETE & event.ev_types | fan.FAN_DELETE_SELF & event.ev_types:
                        self.fs2es_indexer.delete_path(event.path[0].decode('utf-8'))
                    elif fan.FAN_RENAME & event.ev_types:
                        self.fs2es_indexer.delete_path(event.path[0].decode('utf-8'))
                        self.fs2es_indexer.import_path(event.path[1].decode('utf-8'))

                # TODO timeout!
        except Exception as err:
            print('STOP')
            print(err)

        self.fanotify_client.close()
        self.fanotify.stop()
