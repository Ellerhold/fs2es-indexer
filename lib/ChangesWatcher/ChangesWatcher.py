#-*- coding: utf-8 -*-


class ChangesWatcher(object):
    """ A watcher for filesystem changes """

    def __init__(self, fs2es_indexer):
        self.fs2es_indexer = fs2es_indexer
        self.logger = self.fs2es_indexer.logger

    def start(self) -> bool:
        """ Starts the changes watcher """
        pass

    def watch(self, timeout: float):
        """ Watches for changes until the timeout is reached. """
        pass
