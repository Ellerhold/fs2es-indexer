#-*- coding: utf-8 -*-

import datetime
import elasticsearch
import elasticsearch.helpers
import hashlib
import itertools
import json
import logging
import os
import re
import time
import typing

from lib.ChangesWatcher.AuditLogChangesWatcher import *
try:
    from lib.ChangesWatcher.FanotifyChangesWatcher import *
except:
    # Fanotify is not available!
    # This will lead to an error in __init__() if use_fanotify is set to true
    pass


class Fs2EsIndexer(object):
    """ Indexes filenames and directory names into an ElasticSearch index ready for spotlight search via Samba 4 """

    def __init__(self, config: dict[str, typing.Any], logger):
        """ Constructor """

        self.logger = logger

        self.directories = config.get('directories', [])
        self.dump_documents_on_error = config.get('dump_documents_on_error', False)

        self.daemon_wait_time = config.get('wait_time', '30m')
        re_match = re.match(r'^(\d+)(\w)$', self.daemon_wait_time)
        if re_match:
            suffix = re_match.group(2)
            if suffix == 's':
                self.daemon_wait_seconds = int(re_match.group(1))
            elif suffix == 'm':
                self.daemon_wait_seconds = int(re_match.group(1)) * 60
            elif suffix == 'h':
                self.daemon_wait_seconds = int(re_match.group(1)) * 60 * 60
            elif suffix == 'd':
                self.daemon_wait_seconds = int(re_match.group(1)) * 60 * 60 * 24
            else:
                self.logger.info('Unknown time unit in "wait_time": %s, expected "s", "m", "h" or "d"' % suffix)
                exit(1)
        else:
            self.logger.info('Unknown "wait_time": %s' % self.daemon_wait_time)
            exit(1)

        exclusions = config.get('exclusions', {})
        self.exclusion_strings = exclusions.get('partial_paths', [])
        self.exclusion_reg_exps = exclusions.get('regular_expressions', [])

        if config.get('use_fanotify', False):
            try:
                self.changes_watcher = FanotifyChangesWatcher(self)
            except:
                self.logger.error('Cant use fanotify to watch for filesystem changes. Did you install "pyfanotify"?')
                exit(1)
        else:
            self.changes_watcher = AuditLogChangesWatcher(self, config.get('samba', {}))

        elasticsearch_config = config.get('elasticsearch', {})
        self.elasticsearch_url = elasticsearch_config.get('url', 'http://localhost:9200')
        self.elasticsearch_index = elasticsearch_config.get('index', 'files')
        self.elasticsearch_bulk_size = elasticsearch_config.get('bulk_size', 10000)
        self.index_file_dates = elasticsearch_config.get('index_file_dates', False)

        elasticsearch_index_mapping_file = elasticsearch_config.get('index_mapping', '/etc/fs2es-indexer/es-index-mapping.json')
        with open(elasticsearch_index_mapping_file, 'r') as f:
            self.elasticsearch_expected_index_mapping = json.load(f)

        elasticsearch_index_settings_file = elasticsearch_config.get('index_settings', '/etc/fs2es-indexer/es-index-settings.json')
        with open(elasticsearch_index_settings_file, 'r') as f:
            self.elasticsearch_expected_index_settings = json.load(f)

        if 'user' in elasticsearch_config:
            elasticsearch_auth = (elasticsearch_config['user'], elasticsearch_config['password'])
        else:
            elasticsearch_auth = None

        self.elasticsearch = elasticsearch.Elasticsearch(
            hosts = self.elasticsearch_url,
            http_auth = elasticsearch_auth,
            max_retries = 10,
            retry_on_timeout = True,
            verify_certs = elasticsearch_config.get('verify_certs', True),
            ssl_show_warn = elasticsearch_config.get('ssl_show_warn', True),
            ca_certs = elasticsearch_config.get('ca_certs', None)
        )

        self.elasticsearch_document_ids = {}
        self.duration_elasticsearch = 0

    @staticmethod
    def format_count(count):
        return '{:,}'.format(count).replace(',', ' ')

    def elasticsearch_map_path_to_document(self, path: str, filename: str) -> Union[dict, None]:
        """ Maps a file or directory path to an elasticsearch document """

        data = {
            "_op_type": "index",
            "_id": self.elasticsearch_map_path_to_id(path),
            "_source": {
                "path": {
                    "real": path
                },
                "file": {
                    "filename": filename
                }
            }
        }

        if self.index_file_dates:
            try:
                data['_source']['file']['created'] = os.path.getctime(path)
                data['_source']['file']['last_modified'] = os.path.getmtime(path)
            except FileNotFoundError:
                return None

        return data

    @staticmethod
    def elasticsearch_map_path_to_id(path: str):
        """ Maps the path to a unique elasticsearch document ID """
        return hashlib.sha256(path.encode('utf-8', 'surrogatepass')).hexdigest()

    def elasticsearch_bulk_action(self, documents):
        """ Imports documents into elasticsearch or deletes documents from there """

        # See https://elasticsearch-py.readthedocs.io/en/v8.6.2/helpers.html#bulk-helpers

        start_time = time.time()
        try:
            elasticsearch.helpers.bulk(self.elasticsearch, documents, index=self.elasticsearch_index)
        except Exception as err:
            self.logger.info(
                'Failed to bulk import/delete documents into elasticsearch "%s": %s' % (self.elasticsearch_url, str(err))
            )

            if self.dump_documents_on_error:
                filename = '/tmp/fs2es-indexer-failed-documents-%s.json' % datetime.datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
                with open(filename, 'w') as f:
                    json.dump(documents, f)

                self.logger.error(
                    'Dumped the failed documents to %s, please review it and report bugs upstream.' % filename
                )

            exit(1)

        self.duration_elasticsearch += time.time() - start_time

    def elasticsearch_analyze_index(self):
        """
        Analyzes the elasticsearch index and reports back if it should be recreated

        See https://gitlab.com/samba-team/samba/-/blob/master/source3/rpc_server/mdssvc/elasticsearch_mappings.json
        for the fields expected by samba and their mappings to the expected Spotlight results
        """

        if self.elasticsearch.indices.exists(index=self.elasticsearch_index):
            actual_index_settings = self.elasticsearch.indices.get_settings(index=self.elasticsearch_index)

            self.logger.debug('Index settings: %s' % json.dumps(actual_index_settings[self.elasticsearch_index]))

            try:
                self.is_dict_complete(self.elasticsearch_expected_index_settings, actual_index_settings[self.elasticsearch_index]['settings']['index'], 'settings')
            except ValueError as err:
                self.logger.info(err)
                return True

            actual_index_mapping = self.elasticsearch.indices.get_mapping(index=self.elasticsearch_index)
            try:
                self.is_dict_complete(self.elasticsearch_expected_index_mapping, actual_index_mapping[self.elasticsearch_index], 'mapping')
            except ValueError as err:
                self.logger.info(err)
                return True

        return False

    def elasticsearch_prepare_index(self):
        """
        Creates the elasticsearch index and sets the mapping

        See https://gitlab.com/samba-team/samba/-/blob/master/source3/rpc_server/mdssvc/elasticsearch_mappings.json
        for the fields expected by samba and their mappings to the expected Spotlight results
        """

        if self.elasticsearch.indices.exists(index=self.elasticsearch_index):
            recreate_necessary = self.elasticsearch_analyze_index()

            if recreate_necessary:
                self.delete_index()

                self.logger.info('Recreating index "%s" ...' % self.elasticsearch_index)
                self.elasticsearch_create_index()
            else:
                try:
                    self.logger.info('Updating mapping of index "%s" ...' % self.elasticsearch_index)
                    self.elasticsearch.indices.put_mapping(
                        index=self.elasticsearch_index,
                        properties=self.elasticsearch_expected_index_mapping['mappings']['properties']
                    )
                except elasticsearch.exceptions.ConnectionError as err:
                    self.logger.error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
                    exit(1)
                except elasticsearch.exceptions.BadRequestError as err:
                    self.logger.error('Failed to update index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))

                    self.logger.info('Deleting index "%s"...' % self.elasticsearch_index)
                    self.elasticsearch.indices.delete(index=self.elasticsearch_index)

                    self.logger.info('Recreating index "%s" ...' % self.elasticsearch_index)
                    self.elasticsearch_create_index()
                except Exception as err:
                    self.logger.error('Failed to update index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))
                    exit(1)
        else:
            self.logger.info('Creating index "%s" ...' % self.elasticsearch_index)
            self.elasticsearch_create_index()

    def elasticsearch_create_index(self):
        try:
            self.elasticsearch.indices.create(
                index=self.elasticsearch_index,
                mappings=self.elasticsearch_expected_index_mapping['mappings'],
                settings=self.elasticsearch_expected_index_settings
            )
        except elasticsearch.exceptions.ConnectionError as err:
            self.logger.error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            self.logger.error('Failed to create index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)

    def elasticsearch_refresh_index(self):
        """ Refresh the elasticsearch index """

        self.logger.info('Refreshing index "%s" ...' % self.elasticsearch_index)
        start_time = time.time()
        try:
            self.elasticsearch.indices.refresh(index=self.elasticsearch_index)
            self.duration_elasticsearch += time.time() - start_time
        except elasticsearch.exceptions.ConnectionError as err:
            self.logger.error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            self.logger.error(
                'Failed to refresh index "%s" at elasticsearch "%s": %s' % (
                    self.elasticsearch_index,
                    self.elasticsearch_url,
                    str(err)
                )
            )
            exit(1)

    def index_directories(self):
        """ Imports the content of the directories and all of its subdirectories into the elasticsearch index """

        # Copy the document IDs to _old and create a new
        elasticsearch_document_ids_old = self.elasticsearch_document_ids
        self.elasticsearch_document_ids = {}

        paths_total = 0
        documents = []
        documents_to_be_indexed = 0
        documents_indexed = 0
        self.duration_elasticsearch = 0
        start_time = round(time.time())

        self.logger.info('Starting to index the files and directories ...')

        for directory in self.directories:
            self.logger.info('- Starting to index directory "%s" ...' % directory)

            for root, dirs, files in os.walk(directory):
                for name in itertools.chain(files, dirs):
                    full_path = os.path.join(root, name)
                    if self.path_should_be_indexed(full_path, False):
                        document = self.elasticsearch_map_path_to_document(
                            path=full_path,
                            filename=name
                        )

                        if document is None:
                            continue

                        paths_total += 1

                        # TODO Update of last_modified date if self.index_file_dates is true
                        if document['_id'] not in elasticsearch_document_ids_old:
                            # Only add _new_ files and dirs to the index
                            documents.append(document)
                            documents_to_be_indexed += 1

                            if documents_to_be_indexed >= self.elasticsearch_bulk_size:
                                self.elasticsearch_bulk_action(documents)

                                documents = []
                                documents_indexed += documents_to_be_indexed
                                documents_to_be_indexed = 0
                                self.logger.info(
                                    '- %s paths indexed, elasticsearch import lasted %.2f / %.2f min(s)' % (
                                        self.format_count(documents_indexed),
                                        self.duration_elasticsearch / 60,
                                        (time.time() - start_time) / 60
                                    )
                                )

                        try:
                            del elasticsearch_document_ids_old[document['_id']]
                        except:
                            pass

                        self.elasticsearch_document_ids[document['_id']] = 1

            self.logger.info('- Indexing of directory "%s" done.' % directory)

        # Add the remaining documents...
        if documents_to_be_indexed > 0:
            self.logger.info('- Importing remaining documents')

            self.elasticsearch_bulk_action(documents)
            documents_indexed += documents_to_be_indexed

            self.logger.info(
                '- %s paths indexed, elasticsearch import lasted %.2f / %.2f min(s)' % (
                    self.format_count(documents_indexed),
                    self.duration_elasticsearch / 60,
                    (time.time() - start_time) / 60
                )
            )

        old_document_count = len(elasticsearch_document_ids_old)
        if old_document_count > 0:
            # Refresh the index before each delete
            self.elasticsearch_refresh_index()

            # Delete every document in elasticsearch_document_ids_old
            # because the crawler didnt find them during the last run!
            self.logger.info(
                'Deleting %s old document(s) from "%s" ...' % (
                    self.format_count(old_document_count),
                    self.elasticsearch_index
                )
            )

            elasticsearch_document_ids_old_list = list(elasticsearch_document_ids_old.keys())
            start_index = 0
            end_index = self.elasticsearch_bulk_size
            while start_index < old_document_count:
                temp_list = elasticsearch_document_ids_old_list[start_index:end_index]

                delete_start_time = time.time()
                self.elasticsearch.delete_by_query(
                    index=self.elasticsearch_index,
                    query={
                        "terms": {
                            "_id": temp_list
                        }
                    }
                )

                self.duration_elasticsearch += time.time() - delete_start_time

                self.logger.info(
                    '- %s / %s documents deleted.' % (
                        self.format_count(min(end_index, old_document_count)),
                        self.format_count(old_document_count)
                    )
                )

                start_index += self.elasticsearch_bulk_size
                end_index += self.elasticsearch_bulk_size

        self.logger.info('Total paths crawled: %s' % self.format_count(paths_total))
        self.logger.info('New paths indexed: %s' % self.format_count(documents_indexed))
        self.logger.info('Old paths deleted: %s' % self.format_count(old_document_count))
        self.logger.info('Indexing run done after %.2f minutes.' % (max(0, time.time() - start_time) / 60))
        self.logger.info('Elasticsearch import lasted %.2f minutes.' % (max(0, self.duration_elasticsearch) / 60))

    def path_should_be_indexed(self, path: str, test_parent_directory: bool):
        """ Tests if a specific path (dir or file) should be indexed """

        if test_parent_directory:
            # For the audit log monitoring we need to test if the parent directory is in the list of directories
            # that we should index
            parent_dir_is_included = False

            for directory in self.directories:
                if path.startswith(directory):
                    parent_dir_is_included = True
                    break

            if not parent_dir_is_included:
                return False

        for search_string in self.exclusion_strings:
            if search_string in path:
                return False

        for search_reg_exp in self.exclusion_reg_exps:
            if re.match(search_reg_exp, path):
                return False

        return True

    def clear_index(self):
        """ Deletes all documents in the elasticsearch index """
        self.elasticsearch_refresh_index()

        self.logger.info('Deleting all documents from index "%s" ...' % self.elasticsearch_index)
        try:
            resp = self.elasticsearch.delete_by_query(
                index=self.elasticsearch_index,
                query={"match_all": {}}
            )

            self.logger.info('Deleted %d documents.' % resp['deleted'])
        except elasticsearch.exceptions.ConnectionError as err:
            self.logger.error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            self.logger.error(
                'Failed to delete all documents of index "%s" at elasticsearch "%s": %s' % (
                    self.elasticsearch_index,
                    self.elasticsearch_url,
                    str(err)
                )
            )
            exit(1)

    def delete_index(self):
        """ Deletes the index """
        self.logger.info('Deleting index "%s"...' % self.elasticsearch_index)
        self.elasticsearch.indices.delete(index=self.elasticsearch_index)

    def daemon(self):
        """ Starts the daemon mode of the indexer"""
        self.logger.info('Starting indexing in daemon mode with a wait time of %s between indexing runs.' % self.daemon_wait_time)

        changes_watcher_active = self.changes_watcher.start()

        self.elasticsearch_prepare_index()

        # Get all document IDs from ES and add new paths to it
        self.elasticsearch_get_all_ids()
        self.index_directories()

        while True:
            if changes_watcher_active:
                changes = self.changes_watcher.watch(self.daemon_wait_seconds)
                self.logger.info('%d filesystem changes in this waiting period handled.' % changes)
            else:
                self.logger.info('No changes-watcher is active, starting next indexing run in %s.' % self.daemon_wait_time)
                time.sleep(self.daemon_wait_seconds)

            self.index_directories()

    def search(self, search_path: str, search_term=None, search_filename=None, verbose: bool = False):
        """
        Searches for a specific term in the ES index

        For the records, the exact query Samba generates for filename (or directory name) queries are either
        1. for a search on the file or directory name (macOS Spotlight search on kMDItemFSName attribute):
        { "_source": ["path.real"], "query": { "query_string": { "query": "(file.filename:Molly*) AND path.real.fulltext:\"/srv/samba/spotlight\"" } } }

        2. for a search on all attributes:
        { "from ": 0, "size": 100, "query": { "query_string ": { "query": "(coron* OR content:coron*) AND path.real.fulltext: \"/storage\" ", "fields": [] } }, "_source": { "includes": [ "path.real" ], "excludes":[] } }

        Enable logging all queries as "slow query" see enable_slowlog() and look into your slow-log-files.
        """

        # TODO explain takes forever!

        # TODO Dont assume "elasticsearch:index = yes", but parse it from smb.conf
        if search_term is not None:
            query = {
                "query_string": {
                    "query": '(*%s* OR content:*%s*) AND path.real.fulltext:"%s"' % (search_term, search_term, search_path)
                }
            }
        elif search_filename is not None:
            query = {
                "query_string": {
                    "query": 'file.filename: *%s* AND path.real.fulltext:"%s"' % (search_filename, search_path)
                }
            }
        else:
            # This will return everything!
            query = {
                "query_string": {
                    "query": 'path.real.fulltext: "%s"' % search_path
                }
            }

        # TODO Dont use the correct index, but parse "elasticsearch:index" (default: _all) from smb.conf
        # See https://elasticsearch-py.readthedocs.io/en/stable/api/elasticsearch.html#elasticsearch.Elasticsearch.search
        try:
            return self.elasticsearch.search(
                index=self.elasticsearch_index,
                query=query,
                explain=verbose,
                from_=0,
                size=100
            )
        except elasticsearch.exceptions.ConnectionError as err:
            self.logger.error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
        except Exception as err:
            self.logger.error(
                'Failed to search for documents of index "%s" at elasticsearch "%s": %s' % (
                    self.elasticsearch_index,
                    self.elasticsearch_url,
                    str(err)
                )
            )

    def elasticsearch_get_all_ids(self):
        """ Reads all document IDs from elasticsearch """
        self.logger.info('Loading all document IDs from elasticsearch...')

        resp = None
        start_time = time.time()

        try:
            resp = self.elasticsearch.search(
                index=self.elasticsearch_index,
                query={
                    "match_all": {}
                },
                stored_fields=[],
                size=self.elasticsearch_bulk_size,
                scroll='1m'
            )
        except elasticsearch.exceptions.ConnectionError as err:
            self.logger.error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            return
        except Exception as err:
            self.logger.error(
                'Failed to search for documents of index "%s" at elasticsearch "%s": %s' % (
                    self.elasticsearch_index,
                    self.elasticsearch_url,
                    str(err)
                )
            )
            return

        while len(resp['hits']['hits']) > 0:
            for document in resp['hits']['hits']:
                self.elasticsearch_document_ids[document['_id']] = 1

            self.logger.debug('- Calling es.scroll() with ID "%s"' % resp['_scroll_id'])

            resp = self.elasticsearch.scroll(
                scroll_id=resp['_scroll_id'],
                scroll='1m'
            )

        self.logger.info(
            'Loaded %s ID(s) from elasticsearch in %.2f min' % (
                self.format_count(len(self.elasticsearch_document_ids)),
                (time.time() - start_time) / 60
            )
        )

    def enable_slowlog(self):
        """ Enables the slow log """
        self.logger.info('Setting the slowlog thresholds on index %s to "0"...' % self.elasticsearch_index)

        self.elasticsearch.indices.put_settings(
            settings={
                "index": {
                    "search": {
                        "slowlog": {
                            "threshold": {
                                "query": {
                                    "warn": "0",
                                    "info": "0",
                                    "debug": "0",
                                    "trace": "0"
                                },
                                "fetch": {
                                    "warn": "0",
                                    "info": "0",
                                    "debug": "0",
                                    "trace": "0"
                                }
                            }
                        }
                    }
                }
            },
            index=self.elasticsearch_index
        )

        self.logger.info('Slowlog for all queries enabled. Do a spotlight search and look into your elasticsearch logs.')

    def disable_slowlog(self):
        """ Disables the slow log """
        self.logger.info('Setting the slowlog thresholds on index %s back to defaults...' % self.elasticsearch_index)

        self.elasticsearch.indices.put_settings(
            settings={
                "index": {
                    "search": {
                        "slowlog": {
                            "threshold": {
                                "query": {
                                    "warn": "-1",
                                    "info": "-1",
                                    "debug": "-1",
                                    "trace": "-1"
                                },
                                "fetch": {
                                    "warn": "-1",
                                    "info": "-1",
                                    "debug": "-1",
                                    "trace": "-1"
                                }
                            }
                        }
                    }
                }
            },
            index=self.elasticsearch_index
        )

        self.logger.info('Slowlog for slow queries only enabled. Only queries that are slow enough are logged to the slowlog again.')


    def import_path(self, path: str) -> int:
        # The path can have a suffix! These are the xattr... ignore them completely
        if ':' in path:
            return 0

        if not self.path_should_be_indexed(path, True):
            return 0

        document = self.elasticsearch_map_path_to_document(
            path=path,
            filename=os.path.basename(path)
        )

        if document is None:
            return 0

        self.logger.debug('*- Import ES doc for "%s"' % path)

        self.elasticsearch_document_ids[document['_id']] = 1

        self.elasticsearch.index(
            index=self.elasticsearch_index,
            id=document['_id'],
            document=document['_source']
        )
        return 1

    def delete_path(self, path: str) -> int:
        if ':' in path:
            # We ignore these paths BECAUSE if you delete a xattr from a file, we don't want to delete the
            # whole file from index.
            return 0

        if not self.path_should_be_indexed(path, True):
            return 0

        self.logger.debug('*- Delete ES doc for "%s"' % path)

        document_id_old = self.elasticsearch_map_path_to_id(path)

        try:
            del self.elasticsearch_document_ids[document_id_old]
        except:
            # If the key was already deleted - thats ok!
            pass

        try:
            self.elasticsearch.delete(
                index=self.elasticsearch_index,
                id=document_id_old
            )
        except elasticsearch.NotFoundError:
            # That's OK, we wanted to delete it anyway
            return 0

        return 1

    def rename_path(self, source_path: str, target_path: str) -> int:
        # If source_path WAS a directory, we have to move all files and subdirectories BELOW it too.
        changes = 0
        resp = self.search(source_path)
        for hit in resp['hits']['hits']:
            # Each of these documents got moved from source_path to target_path!

            hit_old_path = hit['_source']['path']['real']
            changes += self.delete_path(hit['_source']['path']['real'])

            hit_new_path = hit_old_path.replace(source_path, target_path, 1)
            changes += self.import_path(hit_new_path)

        return changes

    def is_dict_complete(self, expected, actual, parent_keys: str):
        """ Compares if all values in expected are present in actual """
        for key, value in expected.items():
            try:
                actual_value = actual[key]
                if type(value) is dict:
                    if type(actual_value) is not dict:
                        raise ValueError(
                            'Expected value in %s%s to be a dict, but was %s!' % (parent_keys, key, type(actual_value))
                        )
                    self.is_dict_complete(value, actual_value, '%s[%s]' % (parent_keys, key))

                if value != actual_value:
                    raise ValueError(
                        'Expected value in %s[%s] to be "%s", but was "%s"!' % (parent_keys, key, value, actual_value)
                    )
            except KeyError:
                raise ValueError('Missing %s[%s]!' % (parent_keys, key))
