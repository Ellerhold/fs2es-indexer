#!/usr/bin/env python3
#-*- coding: utf-8 -*-

import argparse
import logging
import re
import time
import yaml

from fs2es_indexer.Fs2EsIndexer import *


def main() -> None:
    parser = argparse.ArgumentParser(description='Indexes the names of files and directories into elasticsearch')

    parser.add_argument(
        'action',
        default='index',
        nargs='?',
        help='What do you want to do? "index" (default), "daemon", "search" or "clear"?'
    )

    parser.add_argument(
        '--search-term',
        action='store',
        default=None,
        help='Action "search" only: The term we want to search for in the index'
    )

    parser.add_argument(
        '--search-filename',
        action='store',
        default=None,
        help='Action "search" only: The filename we want to search for in the index'
    )

    parser.add_argument(
        '--search-path',
        action='store',
        help='Action "search" only: The server(!) path we want to search in (use the samba share\'s "path")'
    )

    parser.add_argument(
        '--config',
        action='store',
        dest='configFile',
        default='/etc/fs2es-indexer/config.yml',
        help='The configuration file to be read'
    )

    parser.add_argument(
        '--log-level-es',
        action='store',
        dest='logLevelEs',
        default='ERROR',
        help='The logging level of the elasticsearch plugin (DEBUG, INFO, WARN, ERROR, FATAL).'
    )

    args = parser.parse_args()

    logging.getLogger('elasticsearch').setLevel(args.logLevelEs)

    Fs2EsIndexer.print('Reading config file "%s"' % args.configFile)
    with open(args.configFile, 'r') as stream:
        config = yaml.safe_load(stream)

    indexer = Fs2EsIndexer(config.get('elasticsearch', {}), config.get('exclusions', {}))

    if args.action == 'index':
        indexer.prepare_index()

        indexer.index_directories(config['directories'])
    elif args.action == 'clear':
        indexer.clear_index()
    elif args.action == 'daemon':
        wait_time = config.get('wait_time', '30m')
        re_match = re.match(r'^(\d+)(\w)$', wait_time)
        if re_match:
            if re_match.group(2) == 's':
                wait_seconds = int(re_match.group(1))
            elif re_match.group(2) == 'm':
                wait_seconds = int(re_match.group(1)) * 60
            elif re_match.group(2) == 'h':
                wait_seconds = int(re_match.group(1)) * 60 * 60
            elif re_match.group(2) == 'd':
                wait_seconds = int(re_match.group(1)) * 60 * 60 * 24
            else:
                Fs2EsIndexer.print('Unknown time unit in "wait_time": %s, expected "s", "m", "h" or "d"' % re_match.group(2))
                exit(1)
        else:
            Fs2EsIndexer.print('Unknown "wait_time": %s' % wait_time)
            exit(1)

        Fs2EsIndexer.print(
            'Starting loop of index with a wait time of %s (= %s seconds)' % (wait_time, wait_seconds)
        )

        while True:
            indexer.prepare_index()

            indexer.index_directories(config['directories'])

            Fs2EsIndexer.print('Starting next indexing run in %s (= %s seconds)' % (wait_time, wait_seconds))
            time.sleep(wait_seconds)
    elif args.action == 'search':
        if args.search_path is None:
            parser.error('"search" requires --search-path')

        indexer.search(args.search_path, args.search_term, args.search_filename)
    else:
        Fs2EsIndexer.print('Unknown action "%s", allowed are "index" (default), "daemon", "search" or "clear".' % args.action)


if __name__ == "__main__":
    main()
