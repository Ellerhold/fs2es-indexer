#-*- coding: utf-8 -*-

import pyfanotify as fan
import select
import time

from lib.ChangesWatcher.ChangesWatcher import *


class FanotifyChangesWatcher(ChangesWatcher):
    """ Uses fanotify to watch for changes """

    def __init__(self, fs2es_indexer):
        super().__init__(fs2es_indexer)
        self.fanotify = None
        self.fanotify_client = None
        self.poller = None

    def start(self) -> bool:
        """ Starts the changes watcher """
        self.fanotify = fan.Fanotify(init_fid=True, log=self.fs2es_indexer.logger.getChild('pyfanotify'))

        # See https://man7.org/linux/man-pages/man2/fanotify_mark.2.html
        event_types = (fan.FAN_CREATE | fan.FAN_DELETE | fan.FAN_DELETE_SELF | fan.FAN_RENAME | fan.FAN_ONDIR)

        for directory in self.fs2es_indexer.directories:
            self.fanotify.mark(
                directory,
                is_type='fs',
                ev_types=event_types
            )

        self.fanotify.start()

        self.fanotify_client = fan.FanotifyClient(self.fanotify, path_pattern='*')
        self.poller = select.poll()
        self.poller.register(self.fanotify_client.sock.fileno(), select.POLLIN)

        return True

    def watch(self, timeout: float):
        """ Watches for changes via fanotify until the timeout is reached. """

        stop_at = time.time() + timeout
        self.logger.info('Monitoring changes via fanotify until next indexing run in %s seconds.' % timeout)

        changes = 0
        while time.time() <= stop_at:
            poll_timeout = stop_at - time.time()
            self.logger.debug('Polling for fanotify events with timeout %d seconds.' % poll_timeout)
            # Wait for next event with a timeout (in ms)
            self.poller.poll(poll_timeout * 1000)
            for event in self.fanotify_client.get_events():
                if fan.FAN_CREATE & event.ev_types:
                    changes += self.fs2es_indexer.import_path(event.path[0].decode('utf-8'))
                elif fan.FAN_DELETE & event.ev_types | fan.FAN_DELETE_SELF & event.ev_types:
                    changes += self.fs2es_indexer.delete_path(event.path[0].decode('utf-8'))
                elif fan.FAN_RENAME & event.ev_types:
                    changes += self.fs2es_indexer.rename_path(
                        event.path[0].decode('utf-8'),
                        event.path[1].decode('utf-8'),
                    )

        self.logger.info('%d filesystem changes in this waiting period handled.' % changes)
