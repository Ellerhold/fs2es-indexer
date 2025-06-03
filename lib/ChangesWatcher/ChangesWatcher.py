#-*- coding: utf-8 -*-


class ChangesWatcher(object):
    """ A watcher for filesystem changes """

    def __init__(self, indexer):
        self.indexer = indexer
        self.logger = self.indexer.logger

    def start(self) -> bool:
        """ Starts the changes watcher """
        pass

    def watch(self, timeout: float) -> int:
        """ Watches for changes until the timeout is reached. """
        pass
