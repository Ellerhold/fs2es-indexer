#-*- coding: utf-8 -*-

import datetime
import elasticsearch
import elasticsearch.helpers
import hashlib
import itertools
import json
import os
import re
import time


class Fs2EsIndexer(object):
    """ Indexes filenames and directory names into an ElasticSearch index ready for spotlight search via Samba 4 """

    def __init__(self, config, verbose_messages):
        """ Constructor """

        self.directories = config.get('directories', [])
        self.dump_documents_on_error = config.get('dump_documents_on_error', False)
        self.verbose_messages = verbose_messages

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
                Fs2EsIndexer.print(
                    'Unknown time unit in "wait_time": %s, expected "s", "m", "h" or "d"' % suffix)
                exit(1)
        else:
            Fs2EsIndexer.print('Unknown "wait_time": %s' % self.daemon_wait_time)
            exit(1)

        exclusions = config.get('exclusions', {})
        self.exclusion_strings = exclusions.get('partial_paths', [])
        self.exclusion_reg_exps = exclusions.get('regular_expressions', [])

        samba_config = config.get('samba', {})
        self.samba_audit_log = samba_config.get('audit_log', None)
        self.samba_monitor_sleep_time = samba_config.get('monitor_sleep_time', 1)

        elasticsearch_config = config.get('elasticsearch', {})
        self.elasticsearch_url = elasticsearch_config.get('url', 'http://localhost:9200')
        self.elasticsearch_index = elasticsearch_config.get('index', 'files')
        self.elasticsearch_bulk_size = elasticsearch_config.get('bulk_size', 10000)
        self.elasticsearch_index_mapping_file = elasticsearch_config.get('index_mapping', '/opt/fs2es-indexer/es-index-mapping.json')

        self.elasticsearch_lib_version = elasticsearch_config.get('library_version', 8)
        if self.elasticsearch_lib_version != 7 and self.elasticsearch_lib_version != 8:
            self.print(
                'This tool only works with the elasticsearch library v7 or v8. Your configured version "%s" is not supported currently.' % self.elasticsearch_lib_version
            )

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

    def elasticsearch_map_path_to_document(self, path, filename):
        """ Maps a file or directory path to an elasticsearch document """

        return {
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

    @staticmethod
    def elasticsearch_map_path_to_id(path):
        """ Maps the path to a unique elasticsearch document ID """
        return hashlib.sha256(path.encode('utf-8', 'surrogatepass')).hexdigest()

    def elasticsearch_bulk_action(self, documents):
        """ Imports documents into elasticsearch or deletes documents from there """

        # See https://elasticsearch-py.readthedocs.io/en/v8.6.2/helpers.html#bulk-helpers

        start_time = time.time()
        try:
            elasticsearch.helpers.bulk(self.elasticsearch, documents, index=self.elasticsearch_index)
        except Exception as err:
            self.print(
                'Failed to bulk import/delete documents into elasticsearch "%s": %s' % (self.elasticsearch_url, str(err))
            )

            if self.dump_documents_on_error:
                filename = '/tmp/fs2es-indexer-failed-documents-%s.json' % datetime.datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
                with open(filename, 'w') as f:
                    json.dump(documents, f)

                self.print_error(
                    'Dumped the failed documents to %s, please review it and report bugs upstream.' % filename
                )

            exit(1)

        self.duration_elasticsearch += time.time() - start_time

    def elasticsearch_prepare_index(self):
        """
        Creates the elasticsearch index and sets the mapping

        See https://gitlab.com/samba-team/samba/-/blob/master/source3/rpc_server/mdssvc/elasticsearch_mappings.json
        for the fields expected by samba and their mappings to the expected Spotlight results
        """

        with open(self.elasticsearch_index_mapping_file, 'r') as f:
            index_mapping = json.load(f)

        if self.elasticsearch.indices.exists(index=self.elasticsearch_index):
            try:
                self.print('Updating mapping of index "%s" ...' % self.elasticsearch_index, end='')
                if self.elasticsearch_lib_version == 7:
                    self.elasticsearch.indices.put_mapping(
                        index=self.elasticsearch_index,
                        doc_type=None,
                        body=index_mapping['mappings']
                    )
                elif self.elasticsearch_lib_version == 8:
                    self.elasticsearch.indices.put_mapping(
                        index=self.elasticsearch_index,
                        properties=index_mapping['mappings']['properties']
                    )

                print(' done.')
            except elasticsearch.exceptions.ConnectionError as err:
                self.print_error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
                exit(1)
            except elasticsearch.exceptions.BadRequestError as err:
                print('')
                self.print_error('Failed to update index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))

                self.print('- Deleting index "%s"...' % self.elasticsearch_index)
                self.elasticsearch.indices.delete(index=self.elasticsearch_index)

                self.print('- Recreating index "%s" ...' % self.elasticsearch_index, end='')
                self.elasticsearch_create_index(index_mapping)
                print(' done.')
            except Exception as err:
                print('')
                self.print_error('Failed to update index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))
                exit(1)
        else:
            self.print('- Creating index "%s" ...' % self.elasticsearch_index, end='')
            self.elasticsearch_create_index(index_mapping)
            print(' done.')

    def elasticsearch_create_index(self, index_mapping):
        try:
            if self.elasticsearch_lib_version == 7:
                self.elasticsearch.indices.create(
                    index=self.elasticsearch_index,
                    body=index_mapping
                )
            elif self.elasticsearch_lib_version == 8:
                self.elasticsearch.indices.create(
                    index=self.elasticsearch_index,
                    mappings=index_mapping['mappings']
                )
        except elasticsearch.exceptions.ConnectionError as err:
            print('')
            self.print_error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            print('')
            self.print_error('Failed to create index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)

    def elasticsearch_refresh_index(self):
        """ Refresh the elasticsearch index """

        self.print('Refreshing index "%s" ...' % self.elasticsearch_index, end='')
        start_time = time.time()
        try:
            self.elasticsearch.indices.refresh(index=self.elasticsearch_index)
            self.duration_elasticsearch += time.time() - start_time
            print(' done.')
        except elasticsearch.exceptions.ConnectionError as err:
            print('')
            self.print_error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            print('')
            self.print_error(
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

        documents = []
        documents_to_be_indexed = 0
        documents_indexed = 0
        self.duration_elasticsearch = 0
        start_time = round(time.time())

        self.print('Starting to index the files and directories ...')

        for directory in self.directories:
            self.print('- Starting to index directory "%s" ...' % directory)

            for root, dirs, files in os.walk(directory):
                for name in itertools.chain(files, dirs):
                    full_path = os.path.join(root, name)
                    if self.path_should_be_indexed(full_path, False):
                        try:
                            document = self.elasticsearch_map_path_to_document(
                                path=full_path,
                                filename=name
                            )
                        except FileNotFoundError:
                            # File/Dir does not exist anymore? Don't index it!
                            document = None

                        if document is not None :
                            if document['_id'] not in elasticsearch_document_ids_old:
                                # Only add _new_ files and dirs to the index
                                documents.append(document)
                                documents_to_be_indexed += 1

                                if documents_to_be_indexed >= self.elasticsearch_bulk_size:
                                    self.elasticsearch_bulk_action(documents)

                                    documents = []
                                    documents_indexed += documents_to_be_indexed
                                    documents_to_be_indexed = 0
                                    self.print(
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

            self.print('- Indexing of directory "%s" done.' % directory)

        # Add the remaining documents...
        if documents_to_be_indexed > 0:
            self.print('- importing remaining documents', end='')
            self.elasticsearch_bulk_action(documents)
            documents_indexed += documents_to_be_indexed
            print(
                ', %s paths indexed, elasticsearch import lasted %.2f / %.2f min(s)' % (
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
            self.print(
                'Deleting %s old document(s) from "%s" ...' % (
                    self.format_count(old_document_count),
                    self.elasticsearch_index
                )
            )

            elasticsearch_document_ids_old_list = list(elasticsearch_document_ids_old.keys())
            start_index = 0
            end_index = self.elasticsearch_bulk_size
            while start_index < old_document_count:
                if self.elasticsearch_lib_version == 7:
                    self.elasticsearch.delete_by_query(
                        index=self.elasticsearch_index,
                        body={
                            "query": {
                                "terms": {
                                    "_id": elasticsearch_document_ids_old_list[start_index:end_index]
                                }
                            }
                        }
                    )
                elif self.elasticsearch_lib_version == 8:
                    self.elasticsearch.delete_by_query(
                        index=self.elasticsearch_index,
                        query={
                            "terms": {
                                "_id": elasticsearch_document_ids_old_list[start_index:end_index]
                            }
                        }
                    )

                self.print('- %s documents deleted.' % self.format_count(end_index))
                start_index += self.elasticsearch_bulk_size
                end_index += self.elasticsearch_bulk_size

        self.print('Total new paths indexed: %s' % self.format_count(documents_indexed))
        self.print('Indexing run done after %.2f minutes.' % ((time.time() - start_time) / 60))
        self.print('Elasticsearch import lasted %.2f minutes.' % (self.duration_elasticsearch / 60))

    def path_should_be_indexed(self, path, test_parent_directory):
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
        self.print('Deleting all documents from index "%s" ...' % self.elasticsearch_index, end='')
        try:
            if self.elasticsearch_lib_version == 7:
                resp = self.elasticsearch.delete_by_query(
                    index=self.elasticsearch_index,
                    body={"query": {"match_all": {}}}
                )
            elif self.elasticsearch_lib_version == 8:
                resp = self.elasticsearch.delete_by_query(
                    index=self.elasticsearch_index,
                    query={"match_all": {}}
                )

            print(' done. Deleted %d documents.' % resp['deleted'])
        except elasticsearch.exceptions.ConnectionError as err:
            print('')
            self.print_error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            print('')
            self.print_error(
                'Failed to delete all documents of index "%s" at elasticsearch "%s": %s' % (
                    self.elasticsearch_index,
                    self.elasticsearch_url,
                    str(err)
                )
            )
            exit(1)

    def daemon(self):
        """ Starts the daemon mode of the indexer"""
        self.print('Starting indexing in daemon mode with a wait time of %s between indexing runs.' % self.daemon_wait_time)

        samba_audit_log_file = None
        if self.samba_audit_log is not None:
            try:
                samba_audit_log_file = open(self.samba_audit_log, 'r')
                # Go to the end of the file - this is our start!
                samba_audit_log_file.seek(0, 2)

                self.print('Successfully opened %s, will monitor it during wait time.' % self.samba_audit_log)
            except:
                samba_audit_log_file = None
                self.print_error('Error opening %s, cant monitor it.' % self.samba_audit_log)

        self.elasticsearch_prepare_index()

        # Get all document IDs from ES and add new paths to it
        self.elasticsearch_get_all_ids()
        self.index_directories()

        while True:
            if samba_audit_log_file is None:
                self.print('Wont monitor Samba audit log, starting next indexing run in %s.' % self.daemon_wait_time)
                time.sleep(self.daemon_wait_seconds)
            else:
                next_run_at = time.time() + self.daemon_wait_seconds
                self.print('Monitoring Samba audit log until next indexing run in %s.' % self.daemon_wait_time)
                self.monitor_samba_audit_log(samba_audit_log_file, next_run_at)

            self.index_directories()

    def monitor_samba_audit_log(self, samba_audit_log_file, stop_at):
        """ Monitors the given file descriptor for changes until the time stop_at is reached. """

        while time.time() <= stop_at:
            line = samba_audit_log_file.readline()
            if not line:
                # Nothing new in the audit log - sleep for 5 seconds

                time.sleep(self.samba_monitor_sleep_time)
                continue

            self.print_verbose('* Got new line: "%s"' % line.strip())

            re_match = re.match(r'^.*\|(openat|unlinkat|renameat|mkdirat)\|ok\|(.*)$', line)
            if re_match:
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

                path_to_import = None
                path_to_delete = None

                if operation == 'openat':
                    # openat has another value "r" or "w", we only want to react to "w"
                    openat_operation = values.pop()
                    if openat_operation == 'w':
                        path_to_import = values.pop()
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

                    # If path_to_delete WAS a directory, we have to move all files and subdirectories BELOW it too.
                    resp = self.search(source_path)
                    for hit in resp['hits']['hits']:
                        # Each of these documents got moved from source_path to target_path!

                        hit_old_path = hit['_source']['path']['real']
                        self.print_verbose('*- delete "%s"' % hit_old_path)
                        document_id_old = self.elasticsearch_map_path_to_id(hit_old_path)

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
                            pass

                        hit_new_path = hit_old_path.replace(source_path, target_path, 1)
                        self.print_verbose('*- import "%s"' % hit_new_path)
                        document = self.elasticsearch_map_path_to_document(
                            path=hit_new_path,
                            filename=os.path.basename(hit_new_path)
                        )

                        self.elasticsearch_document_ids[document['_id']] = 1

                        self.elasticsearch.index(
                            index=self.elasticsearch_index,
                            id=document['_id'],
                            document=document['_source']
                        )

                elif operation == 'mkdirat':
                    path_to_import = values.pop()
                elif operation == 'unlinkat':
                    path_to_delete = values.pop()
                else:
                    self.print_verbose('*- not interested: unrecognized operation: %s' % operation)
                    continue

                if path_to_import is not None:
                    # The path can have a suffix! These are the xattr... ignore them completely
                    if ':' in path_to_import:
                        continue

                    if self.path_should_be_indexed(path_to_import, True):
                        self.print_verbose('*- import "%s"' % path_to_import)

                        document = self.elasticsearch_map_path_to_document(
                            path=path_to_import,
                            filename=os.path.basename(path_to_import)
                        )

                        self.elasticsearch_document_ids[document['_id']] = 1

                        self.elasticsearch.index(
                            index=self.elasticsearch_index,
                            id=document['_id'],
                            document=document['_source']
                        )

                if path_to_delete is not None:
                    # The path can have a suffix! These are the xattr... ignore them completely
                    if ':' in path_to_delete:
                        # We ignore these paths BECAUSE if you delete a xattr from a file, we don't want to delete the
                        # whole file from index.
                        continue

                    if self.path_should_be_indexed(path_to_delete, True):
                        self.print_verbose('*- delete "%s"' % path_to_delete)

                        document_id_old = self.elasticsearch_map_path_to_id(path_to_delete)

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
                            pass
            else:
                self.print_verbose('*- not interested: regexp didnt match')
                continue

    def search(self, search_path, search_term=None, search_filename=None):
        """
        Searches for a specific term in the ES index

        For the records, the exact query Samba generates for filename (or directory name) queries are either
        1. for a search on the file or directory name (macOS Spotlight search on kMDItemFSName attribute):
        { "_source": ["path.real"], "query": { "query_string": { "query": "(file.filename:Molly*) AND path.real.fulltext:\"/srv/samba/spotlight\"" } } }

        2. for a search on all attributes:
        { "from ": 0, "size": 100, "query": { "query_string ": { "query": "(coron* OR content:coron*) AND path.real.fulltext: \"/storage\" ", "fields": [] } }, "_source": { "includes": [ "path.real" ], "excludes":[] } }

        Enable logging all queries as "slow query" see enable_slowlog() and look into your slow-log-files.
        """

        if search_term is not None:
            query = {
                "query_string": {
                    "query": '(%s* or content:%s*) AND path.real.fulltext:"%s"' % (search_term, search_term, search_path)
                }
            }
        elif search_filename is not None:
            query = {
                "query_string": {
                    "query": 'file.filename: %s* AND path.real.fulltext:"%s"' % (search_term, search_path)
                }
            }
        else:
            # This will return everything!
            query = {
                "query_string": {
                    "query": 'path.real.fulltext: "%s"' % search_path
                }
            }

        try:
            if self.elasticsearch_lib_version == 7:
                return self.elasticsearch.search(
                    index=self.elasticsearch_index,
                    body={
                        "query": query
                    },
                    from_=0,
                    size=100
                )
            elif self.elasticsearch_lib_version == 8:
                return self.elasticsearch.search(
                    index=self.elasticsearch_index,
                    query=query,
                    from_=0,
                    size=100
                )
        except elasticsearch.exceptions.ConnectionError as err:
            self.print_error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
        except Exception as err:
            self.print_error(
                'Failed to search for documents of index "%s" at elasticsearch "%s": %s' % (
                    self.elasticsearch_index,
                    self.elasticsearch_url,
                    str(err)
                )
            )

    def elasticsearch_get_all_ids(self):
        """ Reads all document IDs from elasticsearch """
        self.print('Loading all document IDs from elasticsearch...')

        resp = None
        start_time = time.time()

        try:
            if self.elasticsearch_lib_version == 7:
                resp = self.elasticsearch.search(
                    index=self.elasticsearch_index,
                    body={
                        "query": {
                            "match_all": {}
                        }
                    },
                    stored_fields=[],
                    size=self.elasticsearch_bulk_size,
                    scroll='1m'
                )
            elif self.elasticsearch_lib_version == 8:
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
            self.print_error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            return
        except Exception as err:
            self.print_error(
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

            self.print_verbose('- Calling es.scroll() with ID "%s"' % resp['_scroll_id'])

            resp = self.elasticsearch.scroll(
                scroll_id=resp['_scroll_id'],
                scroll='1m'
            )

        self.print(
            'Loaded %s ID(s) from elasticsearch in %.2f min' % (
                self.format_count(len(self.elasticsearch_document_ids)),
                (time.time() - start_time) / 60
            )
        )

    def enable_slowlog(self):
        """ Enables the slow log """
        self.print('Setting the slowlog thresholds on index %s to "0"...' % self.elasticsearch_index)

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

        self.print('Slowlog for all queries enabled. Do a spotlight search and look into your elasticsearch logs.')

    def disable_slowlog(self):
        """ Disables the slow log """
        self.print('Setting the slowlog thresholds on index %s back to defaults...' % self.elasticsearch_index)

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

        self.print('Slowlog for slow queries only enabled. Only queries that are slow enough are logged to the slowlog again.')

    def print_verbose(self, message, end='\n'):
        """ Prints the given message onto the console and preprends the current datetime IF VERBOSE printing is enabled """
        if self.verbose_messages:
            self.print(message, end)

    @staticmethod
    def print(message, end='\n'):
        """ Prints the given message onto the console and preprends the current datetime """
        print(
            '%s %s' % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message),
            end=end
        )

    @staticmethod
    def print_error(message, end='\n'):
        """ Prints the given message as an error onto the console and preprends the current datetime """
        print(
            '%s %s%s%s' % (
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                '\033[91m',
                message,
                '\033[0m'
            ),
            end=end
        )
