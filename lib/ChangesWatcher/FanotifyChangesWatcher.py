#-*- coding: utf-8 -*-

import os
import pyfanotify as fan
import select
import time

from lib.ChangesWatcher.ChangesWatcher import *

# Not every pyfanotify version exports FAN_ATTRIB, the value is fixed in linux/fanotify.h
FAN_ATTRIB = getattr(fan, 'FAN_ATTRIB', 0x00000004)


class FanotifyChangesWatcher(ChangesWatcher):
    """ Uses fanotify to watch for changes """

    def __init__(self, indexer):
        super().__init__(indexer)
        self.fanotify = None
        self.fanotify_client = None
        self.poller = None

    def start(self) -> bool:
        """ Starts the changes watcher """
        self.fanotify = fan.Fanotify(init_fid=True, log=self.indexer.logger.getChild('pyfanotify'))

        # See https://man7.org/linux/man-pages/man2/fanotify_mark.2.html
        event_types = (fan.FAN_CREATE | fan.FAN_DELETE | fan.FAN_DELETE_SELF | fan.FAN_RENAME | fan.FAN_ONDIR)

        if len(self.indexer.auto_delete_files) > 0 or len(self.indexer.auto_remove_xattrs) > 0:
            # Only add the events if necessary
            event_types = event_types | fan.FAN_CLOSE_WRITE | fan.FAN_CLOSE_NOWRITE

        if len(self.indexer.auto_remove_xattrs) > 0:
            # Samba may set xattrs (e.g. macOS streams) after the last close of the file
            event_types = event_types | FAN_ATTRIB

        for directory in self.indexer.directories:
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

    def watch(self, timeout: float) -> int:
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
                    changes += self.indexer.import_path_into_elasticsearch(event.path[0].decode('utf-8'))
                elif fan.FAN_DELETE & event.ev_types or fan.FAN_DELETE_SELF & event.ev_types:
                    changes += self.indexer.delete_path_from_elasticsearch(event.path[0].decode('utf-8'))
                elif fan.FAN_RENAME & event.ev_types:
                    changes += self.indexer.rename_path_in_elasticsearch(
                        event.path[0].decode('utf-8'),
                        event.path[1].decode('utf-8'),
                    )
                elif fan.FAN_CLOSE_WRITE & event.ev_types or fan.FAN_CLOSE_NOWRITE & event.ev_types:
                    # Delete this file on close (when writing to it is done).
                    self.indexer.handle_auto_deletion(event.path[0].decode('utf-8'))

                if (fan.FAN_CLOSE_WRITE | fan.FAN_CLOSE_NOWRITE | FAN_ATTRIB) & event.ev_types:
                    # Events can be merged (e.g. FAN_CREATE | FAN_ATTRIB), so this is no elif
                    self.indexer.handle_auto_xattr_removal(event.path[0].decode('utf-8'))


        return changes
