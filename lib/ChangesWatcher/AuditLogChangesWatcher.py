#-*- coding: utf-8 -*-

import os
import time
import typing

from lib.ChangesWatcher.ChangesWatcher import *


class AuditLogChangesWatcher(ChangesWatcher):
    """ Watches the samba audit.log for fileystem changes """

    def __init__(self, fs2es_indexer, samba_config: dict[str, typing.Any]):
        super().__init__(fs2es_indexer)

        self.samba_audit_log = samba_config.get('audit_log', None)
        self.samba_monitor_sleep_time = samba_config.get('monitor_sleep_time', 1)
        self.samba_audit_log_file = None

    def start(self) -> bool:
        """ Starts the changes watcher """
        self.samba_audit_log_file = None
        if self.samba_audit_log is None:
            return False

        try:
            self.samba_audit_log_file = open(self.samba_audit_log, 'r')
            # Go to the end of the file - this is our start!
            self.samba_audit_log_file.seek(0, 2)

            self.print('Successfully opened %s, will monitor it during wait time.' % self.samba_audit_log)
            return True
        except:
            self.samba_audit_log_file = None
            self.print_error('Error opening %s, cant monitor it.' % self.samba_audit_log)
            return False

    def watch(self, timeout: float):
        """ Monitors the given file descriptor for changes until the timeout is reached. """

        stop_at = time.time() + timeout
        self.print('Monitoring Samba audit log until next indexing run in %s seconds.' % timeout)

        while time.time() <= stop_at:
            line = self.samba_audit_log_file.readline()
            if not line:
                # Was the file log rotated?
                # logrotate's copytruncate works by copying the file and removing the contents of the original
                #   In this case the size of the file now would be drastically (!) less than our current position.
                #   We'll reopen the file without (!) seeking to the end.
                # Without "copytruncate" the current file is renamed and a new file is created.
                #   We need to close the old file handle (now pointing to the backup) and open the new file
                #   (at the old location). The problem is, that this new file WILL be created AFTER the rename and
                #   we could possible try to read in between! So we have to test if the file exist and possibly wait a
                #   bit before we try again.
                try:
                    file_was_rotated = self.samba_audit_log_file.tell() > os.path.getsize(self.samba_audit_log)
                    if file_was_rotated:
                        self.print('Samba audit log was rotated and a new file exists at "%s".' % self.samba_audit_log)
                except FileNotFoundError:
                    # The new file does not exist yet! We need to wait a bit...
                    file_was_rotated = True
                    self.print('Samba audit log was rotated and no new file does exist at "%s".' % self.samba_audit_log)
                    time.sleep(self.samba_monitor_sleep_time)

                if file_was_rotated:
                    self.print('Reopening Samba audit log "%s"...' % self.samba_audit_log)
                    self.samba_audit_log_file.close()
                    self.samba_audit_log_file = None
                    while time.time() <= stop_at and self.samba_audit_log_file is None:
                        try:
                            self.samba_audit_log_file = open(self.samba_audit_log, 'r')
                            self.print('Samba audit log was successfully reopened.')
                        except FileNotFoundError:
                            # The new file does not exist yet ... wait a little bit and try again
                            self.print('Samba audit log couldnt be reopened...')
                            time.sleep(self.samba_monitor_sleep_time)

                    if self.samba_audit_log_file is None:
                        self.print('Samba audit log couldnt be reopened! Disabling the audit log monitoring.')

                    continue

                else:
                    # Nothing new in the audit log - sleep for X seconds

                    time.sleep(self.samba_monitor_sleep_time)
                    continue

            self.print_verbose('* Got new line: "%s"' % line.strip())

            re_match = re.match(r'^.*\|(openat|unlinkat|renameat|mkdirat)\|ok\|(.*)$', line)
            if not re_match:
                self.print_verbose('*- not interested: regexp didnt match')
                continue

            # create a file:       <user>|<ip>|openat|ok|w|<path> (w!)
            # rename a file / dir: <user>|<ip>|renameat|ok|<source>|<target>
            # create a dir:        <user>|<ip>|mkdirat|ok|<path>
            # delete a file / dir: <user>|<ip>|unlinkat|ok|<path>

            operation = re_match.group(1)
            values = re_match.group(2).split('|')

            if len(values) == 0:
                if self.print_verbose:
                    self.print_verbose('*- not interested: no values?!')
                continue

            # So we can use pop(), because python has no array_shift()!
            values.reverse()

            if operation == 'openat':
                # openat has another value "r" or "w", we only want to react to "w"
                openat_operation = values.pop()
                if openat_operation == 'w':
                    self.fs2es_indexer.import_path(values.pop())
                else:
                    self.print_verbose('*- not interested: expected openat with w, but got "%s"' % openat_operation)

            elif operation == 'renameat':
                source_path = values.pop()
                target_path = values.pop()

                if ':' in source_path:
                    # We ignore these paths BECAUSE if you delete a xattr from a file, we don't want to delete the
                    # whole file from index.
                    # This should not happen for a renameat, but oh well...
                    continue

                self.fs2es_indexer.rename_path(
                    source_path,
                    target_path,
                )

            elif operation == 'mkdirat':
                self.fs2es_indexer.import_path(values.pop())
            elif operation == 'unlinkat':
                self.fs2es_indexer.delete_path(values.pop())
            else:
                self.print_verbose('*- not interested: unrecognized operation: %s' % operation)
                continue
