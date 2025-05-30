#-*- coding: utf-8 -*-

from lib import *


class ChangesWatcher(object):
    """A watcher for changes"""

    def __init__(self, fs2es_indexer: Fs2EsIndexer):
        self.fs2es_indexer = fs2es_indexer

    @staticmethod
    def print(message: str, end: str = '\n'):
        """ Prints the given message onto the console and preprends the current datetime """
        self.fs2es_indexer.print(message, end)

    def print_verbose(self, message: str, end: str = '\n'):
        """ Prints the given message onto the console and preprends the current datetime IF VERBOSE printing is enabled """
        self.fs2es_indexer.print_verbose(message, end)

    @staticmethod
    def print_error(message: str, end: str = '\n'):
        """ Prints the given message as an error onto the console and preprends the current datetime """
        self.fs2es_indexer.print_error(message, end)

    def start(self) -> bool:
        """ Starts the changes watcher """
        pass

    def watch(self, timeout: float):
        """ Watches for changes until the timeout is reached. """
        pass
