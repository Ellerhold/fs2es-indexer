#-*- coding: utf-8 -*-

import datetime
import elasticsearch
import elasticsearch.helpers
import hashlib
import json
import os
import re
import time


class Fs2EsIndexer(object):
    """ Indexes filenames and directory names into an ElasticSearch index ready for spotlight search via Samba 4 """

    def __init__(self, elasticsearch_config, exclusions):
        """ Constructor """

        self.elasticsearch_url = elasticsearch_config.get('url', 'http://localhost:9200')
        self.elasticsearch_index = elasticsearch_config.get('index', 'files')
        self.elasticsearch_bulk_size = elasticsearch_config.get('bulk_size', 10000)
        self.elasticsearch_lib_version = elasticsearch_config.get('library_version', 8)
        self.exclusion_strings = exclusions.get('partial_paths', [])
        self.exclusion_reg_exps = exclusions.get('regular_expressions', [])

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

    def map_path_to_es_document(self, path, filename, index_time):
        """ Maps a file or directory path to an elasticsearch document """
        return {
            "_index": self.elasticsearch_index,
            "_id": hashlib.sha1(path.encode('utf-8')).hexdigest(),
            "_source": {
                "path": {
                    "real": path
                },
                "file": {
                    "filename": filename,
                    "filesize": os.path.getsize(path)
                },
                "time": index_time
            }
        }

    def bulk_import_into_es(self, documents):
        """ Imports documents into elasticsearch """
        try:
            elasticsearch.helpers.bulk(self.elasticsearch, documents)
        except Exception as err:
            self.print(
                'Failed to bulk import documents into elasticsearch "%s": %s' % (self.elasticsearch_url, str(err))
            )
            exit(1)

    def prepare_index(self):
        """
        Creates the elasticsearch index and sets the mapping

        See https://gitlab.com/samba-team/samba/-/blob/master/source3/rpc_server/mdssvc/elasticsearch_mappings.json
        for the fields expected by samba and their mappings to the expected Spotlight results
        """
        index_mapping = {
            "mappings": {
                "properties": {
                    "path": {
                        "properties": {
                            "real": {
                                "type": "keyword",
                                "store": True,
                                "fields": {
                                    "tree": {
                                        "type": "text",
                                        "fielddata": True
                                    },
                                    "fulltext": {
                                        "type": "text"
                                    }
                                }
                            }
                        }
                    },
                    "file": {
                        "properties": {
                            "filename": {
                                "type": "keyword",
                                "store": True,
                                "fields": {
                                    "tree": {
                                        "type": "text",
                                        "fielddata": True
                                    },
                                    "fulltext": {
                                        "type": "text"
                                    }
                                }
                            },
                            "filesize": {
                                "type": "unsigned_long",
                                "store": True
                            }
                        }
                    },
                    "time": {
                        "type": "long"
                    }
                }
            }
        }

        if self.elasticsearch.indices.exists(index=self.elasticsearch_index):
            try:
                self.print('- Updating mapping of index "%s" ...' % self.elasticsearch_index)
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

                self.print('- Mapping of index "%s" successfully updated' % self.elasticsearch_index)
            except elasticsearch.exceptions.ConnectionError as err:
                self.print('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
                exit(1)
            except Exception as err:
                self.print('Failed to create index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))
                exit(1)
        else:
            self.print('- Creating index "%s" ...' % self.elasticsearch_index)

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

                self.print('- Index "%s" successfully created' % self.elasticsearch_index)
            except elasticsearch.exceptions.ConnectionError as err:
                self.print('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
                exit(1)
            except Exception as err:
                self.print('Failed to create index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))
                exit(1)

    def index_directories(self, directories):
        """ Imports the content of the directories and all of its sub directories into the elasticsearch index """
        documents = []
        documents_indexed = 0
        index_time = time.time()

        for directory in directories:
            self.print('- Indexing of files and directories in "%s" ...' % directory)
            for root, dirs, files in os.walk(directory):
                for name in files:
                    full_path = os.path.join(root, name)
                    if self.path_should_be_indexed(full_path):
                        try:
                            documents.append(self.map_path_to_es_document(full_path, name, index_time))
                        except FileNotFoundError:
                            """ File does not exist anymore? Dont index it! """
                            pass

                        if len(documents) >= self.elasticsearch_bulk_size:
                            self.print('- Files & directories indexed in "%s": ' % directory, end='')
                            self.bulk_import_into_es(documents)
                            documents_indexed += self.elasticsearch_bulk_size
                            print(documents_indexed)
                            documents = []

                for name in dirs:
                    full_path = os.path.join(root, name)
                    if self.path_should_be_indexed(full_path):
                        try:
                            documents.append(self.map_path_to_es_document(full_path, name, index_time))
                        except FileNotFoundError:
                            """ File does not exist anymore? Dont index it! """
                            pass

                        if len(documents) >= self.elasticsearch_bulk_size:
                            self.print('- Files & directories indexed in "%s": ' % directory, end='')
                            self.bulk_import_into_es(documents)
                            documents_indexed += self.elasticsearch_bulk_size
                            print(documents_indexed)
                            documents = []

        # Add the remaining documents...
        self.print('- Files & directories indexed: ', end='')
        self.bulk_import_into_es(documents)
        documents_indexed += len(documents)
        print(documents_indexed)

        self.clear_old_documents(index_time)

        self.print(
            '- Indexing run done after %.2f minutes.' % ((time.time() - index_time) / 60)
       )

    def path_should_be_indexed(self, path):
        """ Tests if a specific path (dir or file) should be indexed """
        for search_string in self.exclusion_strings:
            if search_string in path:
                return False

        for search_reg_exp in self.exclusion_reg_exps:
            if re.match(search_reg_exp, path):
                return False

        return True

    def clear_old_documents(self, index_time):
        """ Deletes old documents from the elasticsearch index """

        # We have to refresh the index first because we most likely updated some documents,
        # and we would run into a version conflict!

        self.print('- Refreshing index "%s" ...' % self.elasticsearch_index)
        try:
            self.elasticsearch.indices.refresh(index=self.elasticsearch_index)
            self.print('- Index "%s" successfully refreshed' % self.elasticsearch_index)
        except elasticsearch.exceptions.ConnectionError as err:
            self.print('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            self.print(
                'Failed to refresh index "%s" at elasticsearch "%s": %s'
                % (self.elasticsearch_index, self.elasticsearch_url, str(err))
            )
            exit(1)

        self.print('- Deleting old documents from "%s" ...' % self.elasticsearch_index)
        try:
            if self.elasticsearch_lib_version == 7:
                resp = self.elasticsearch.delete_by_query(
                    index=self.elasticsearch_index,
                    body={
                        "query": {
                            "range": {
                                "time": {
                                    "lt": index_time - 1
                                }
                            }
                        }
                    }
                )
            elif self.elasticsearch_lib_version == 8:
                resp = self.elasticsearch.delete_by_query(
                    index=self.elasticsearch_index,
                    query={
                        "range": {
                            "time": {
                                "lt": index_time - 1
                            }
                        }
                    }
                )

            self.print('- Deleted %d old documents from "%s"' % (resp['deleted'], self.elasticsearch_index))
        except elasticsearch.exceptions.ConnectionError as err:
            self.print('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            self.print(
                'Failed to delete old documents of index "%s" at elasticsearch "%s": %s'
                % (self.elasticsearch_index, self.elasticsearch_url, str(err))
            )
            exit(1)

    def clear_index(self):
        """ Deletes all documents in the elasticsearch index """
        self.print('- Deleting all documents from index "%s" ...' % self.elasticsearch_index)
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

            self.print('- Deleted all %d documents from "%s"' % (resp['deleted'], self.elasticsearch_index))
        except elasticsearch.exceptions.ConnectionError as err:
            self.print('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            self.print(
                'Failed to delete all documents of index "%s" at elasticsearch "%s": %s'
                % (self.elasticsearch_index, self.elasticsearch_url, str(err))
            )
            exit(1)

    def search(self, search_path, search_term=None, search_filename=None):
        """
        Searches for a specific term in the ES index

        For the records, the exact query Samba generates for filename (or directory name) queries are either
        1. for a search on the file or directory name (macOS Spotlight search on kMDItemFSName attribute):
        { "_source": ["path.real"], "query": { "query_string": { "query": "(file.filename:Molly*) AND path.real.fulltext:\"/srv/samba/spotlight\"" } } }

        2. for a search on all attributes:
        { "_source": ["path.real"], "query": { "query_string": { "query": "(Molly*) AND path.real.fulltext:\"/srv/samba/spotlight\"" } } }

        Enable logging all queries as "slow query":
        PUT /files/_settings
        {
          "index.search.slowlog.threshold.query.warn": "1ms",
          "index.search.slowlog.threshold.query.info": "1ms",
          "index.search.slowlog.threshold.query.debug": "1ms",
          "index.search.slowlog.threshold.query.trace": "1ms",
          "index.search.slowlog.threshold.fetch.warn": "1ms",
          "index.search.slowlog.threshold.fetch.info": "1ms",
          "index.search.slowlog.threshold.fetch.debug": "1ms",
          "index.search.slowlog.threshold.fetch.trace": "1ms"
        }

        and look into your slow-log-files.
        """

        if search_term is not None:
            query = {
                "query_string": {
                    "query": '%s* AND path.real.fulltext:"%s"' % (search_term, search_path)
                }
            }
        elif search_filename is not None:
            query = {
                "query_string": {
                    "query": 'file.filename: %s* AND path.real.fulltext:"%s"' % (search_term, search_path)
                }
            }
        else:
            """ This will return everything! """
            query = {
                "query_string": {
                    "query": 'path.real.fulltext: "%s"' % search_path
                }
            }

        try:
            if self.elasticsearch_lib_version == 7:
                resp = self.elasticsearch.search(
                    index=self.elasticsearch_index,
                    body={
                        "query": query
                    },
                    from_=0,
                    size=100
                )
            elif self.elasticsearch_lib_version == 8:
                resp = self.elasticsearch.search(
                    index=self.elasticsearch_index,
                    query=query,
                    from_=0,
                    size=100
                )
        except elasticsearch.exceptions.ConnectionError as err:
            self.print('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            self.print(
                'Failed to search for documents of index "%s" at elasticsearch "%s": %s'
                % (self.elasticsearch_index, self.elasticsearch_url, str(err))
            )
            exit(1)

        self.print('Found %d elasticsearch documents:' % resp['hits']['total']['value'])
        for hit in resp['hits']['hits']:
            self.print(
                '- %s: %s' % (hit['_source']['file']['filename'], json.dumps(hit['_source']))
            )

    @staticmethod
    def print(message, end='\n'):
        """ Prints the given message onto the console and preprends the current datetime """
        print(
            '%s %s'
            % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message),
            end=end
        )
