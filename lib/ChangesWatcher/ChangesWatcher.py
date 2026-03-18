#-*- coding: utf-8 -*-


class ChangesWatcher(object):
    """ A watcher for filesystem changes """

    def __init__(self, auto_delete_files, indexer):
        self.indexer = indexer
        self.auto_delete_files = auto_delete_files
        self.logger = self.indexer.logger

    def start(self) -> bool:
        """ Starts the changes watcher """
        pass

    def watch(self, timeout: float) -> int:
        """ Watches for changes until the timeout is reached. """
        pass
