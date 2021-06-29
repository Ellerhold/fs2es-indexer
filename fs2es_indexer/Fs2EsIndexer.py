#-*- coding: utf-8 -*-

import datetime
import elasticsearch
import elasticsearch.helpers
import hashlib
import json
import os
import time


class Fs2EsIndexer(object):
    """ Indexes filenames and directory names into an ElasticSearch index ready for spotlight search via Samba 4 """

    def __init__(self, elasticsearch_config):
        """ Constructor """

        self.elasticsearch_url = elasticsearch_config['url']
        self.elasticsearch_index = elasticsearch_config['index']
        self.elasticsearch_bulk_size = elasticsearch_config['bulk_size']

        if 'user' in elasticsearch_config:
            self.elasticsearch = elasticsearch.Elasticsearch(
                self.elasticsearch_url,
                http_auth=(elasticsearch_config['user'], elasticsearch_config['password'])
            )
        else:
            self.elasticsearch = elasticsearch.Elasticsearch(self.elasticsearch_url)

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
                    "filename": filename
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
        """ Creates the index and sets the mapping """
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
                            }
                        }
                    },
                    "time": {
                        "type": "long"
                    }
                }
            }
        }

        if self.elasticsearch.indices.exists(self.elasticsearch_index):
            try:
                self.print('- Updating mapping of index "%s" ...' % self.elasticsearch_index)
                self.elasticsearch.indices.put_mapping(
                    index=self.elasticsearch_index,
                    doc_type=None,
                    body=json.dumps(index_mapping['mappings'])
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
                self.elasticsearch.indices.create(
                    index=self.elasticsearch_index,
                    body=json.dumps(index_mapping)
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
                    documents.append(self.map_path_to_es_document(full_path, name, index_time))

                    if len(documents) >= self.elasticsearch_bulk_size:
                        self.print('- Files & directories indexed in "%s": ' % directory, end='')
                        self.bulk_import_into_es(documents)
                        documents_indexed += self.elasticsearch_bulk_size
                        print(documents_indexed)
                        documents = []

                for name in dirs:
                    full_path = os.path.join(root, name)
                    documents.append(self.map_path_to_es_document(full_path, name, index_time))

                    if len(documents) >= self.elasticsearch_bulk_size:
                        self.print('- Files & directories indexed in "%s": ' % directory, end='')
                        self.bulk_import_into_es(documents)
                        documents_indexed += self.elasticsearch_bulk_size
                        print(documents_indexed)
                        documents = []

        # Add the remaining documents...
        self.print('- Files & directories indexed: ' % directory, end='')
        self.bulk_import_into_es(documents)
        documents_indexed += len(documents)
        print(documents_indexed)

        self.clear_old_documents(index_time)

    def clear_old_documents(self, index_time):
        """ Deletes old documents from the elasticsearch index """

        # We have to refresh the index first because we most likely updated some of the documents and we would run into
        # a version conflict!

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
            resp = self.elasticsearch.delete_by_query(
                index=self.elasticsearch_index,
                body={"query": {"match_all": {}}}
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

    @staticmethod
    def print(message, end='\n'):
        """ Prints the given message onto the console and preprends the current datetime """
        print(
            '%s %s'
            % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message),
            end=end
        )
