#-*- coding: utf-8 -*-


class ChangesWatcher(object):
    """ A watcher for filesystem changes """

    def __init__(self, fs2es_indexer):
        self.fs2es_indexer = fs2es_indexer

    def print(self, message: str, end: str = '\n'):
        """ Prints the given message onto the console and preprends the current datetime """
        self.fs2es_indexer.print(message, end)

    def print_verbose(self, message: str, end: str = '\n'):
        """ Prints the given message onto the console and preprends the current datetime IF VERBOSE printing is enabled """
        self.fs2es_indexer.print_verbose(message, end)

    def print_error(self, message: str, end: str = '\n'):
        """ Prints the given message as an error onto the console and preprends the current datetime """
        self.fs2es_indexer.print_error(message, end)

    def start(self) -> bool:
        """ Starts the changes watcher """
        pass

    def watch(self, timeout: float):
        """ Watches for changes until the timeout is reached. """
        pass
