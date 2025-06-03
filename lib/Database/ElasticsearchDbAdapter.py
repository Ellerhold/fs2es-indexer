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

from lib.Database.DbAdapter import *


class ElasticsearchDbAdapter(DbAdapter):
    """ An adapter for an elasticsearch database """

    def __init__(self, indexer, elasticsearch_config):
        self.indexer = indexer
        self.logger = self.indexer.logger

        self.elasticsearch_url = elasticsearch_config.get('url', 'http://localhost:9200')
        self.elasticsearch_index = elasticsearch_config.get('index', 'files')
        self.elasticsearch_bulk_size = elasticsearch_config.get('bulk_size', 10000)
        self.elasticsearch_index_mapping_file = elasticsearch_config.get(
            'index_mapping',
            '/opt/fs2es-indexer/es-index-mapping.json'
        )

    def is_usable(self) -> bool:
        """
        Analyzes the elasticsearch index and reports back if it should be recreated

        See https://gitlab.com/samba-team/samba/-/blob/master/source3/rpc_server/mdssvc/elasticsearch_mappings.json
        for the fields expected by samba and their mappings to the expected Spotlight results
        """

        if self.elasticsearch.indices.exists(index=self.elasticsearch_index):
            index_settings = self.elasticsearch.indices.get_settings(index=self.elasticsearch_index)

            self.logger.debug('Index settings: %s' % json.dumps(index_settings[self.elasticsearch_index]))

            try:
                tokenizer = index_settings[self.elasticsearch_index]['settings']['index']['analysis']['analyzer']['default']['tokenizer']
                if tokenizer == self.elasticsearch_tokenizer:
                    self.logger.info('Index "%s" has correct tokenizer "%s".' % (self.elasticsearch_index, tokenizer))
                else:
                    self.logger.info(
                        'Index "%s" has wrong tokenizer "%s", expected "%s" -> recreating the index is necessary'
                        % (self.elasticsearch_index, tokenizer, self.elasticsearch_tokenizer)
                    )
                    return False
            except KeyError:
                self.logger.info('Index "%s" has no tokenizer -> recreating the index is necessary.' % self.elasticsearch_index)
                return False

            try:
                analyzer_filter = index_settings[self.elasticsearch_index]['settings']['index']['analysis']['analyzer']['default']['filter']
                self.logger.info('Index "%s" has analyzer filter(s) "%s".' % (self.elasticsearch_index, '", "'.join(analyzer_filter)))

                if 'lowercase' in analyzer_filter:
                    self.logger.info('Index "%s" has analyzer filter "lowercase".' % self.elasticsearch_index)
                else:
                    self.logger.info(
                        'Index "%s" misses the analyzer filter "lowercase" -> recreating the index is necessary.'
                        % self.elasticsearch_index
                    )
                    return False

                if 'asciifolding' in analyzer_filter:
                    self.logger.info('Index "%s" has analyzer filter "asciifolding".' % self.elasticsearch_index)
                else:
                    self.logger.info(
                        'Index "%s" misses the analyzer filter "asciifolding" -> recreating the index is necessary.'
                        % self.elasticsearch_index
                    )
                    return False
            except KeyError:
                self.logger.info('Index "%s" has no analyzer filter -> recreating the index is necessary.' % self.elasticsearch_index)
                return False

        return True

    def prepare(self):
        """
        Creates the elasticsearch index and sets the mapping

        See https://gitlab.com/samba-team/samba/-/blob/master/source3/rpc_server/mdssvc/elasticsearch_mappings.json
        for the fields expected by samba and their mappings to the expected Spotlight results
        """

        with open(self.elasticsearch_index_mapping_file, 'r') as f:
            index_mapping = json.load(f)

        if self.elasticsearch.indices.exists(index=self.elasticsearch_index):
            if not self.is_usable():
                self.logger.info('Deleting index "%s"...' % self.elasticsearch_index)
                self.elasticsearch.indices.delete(index=self.elasticsearch_index)

                self.logger.info('Recreating index "%s" ...' % self.elasticsearch_index)
                self.create_index(index_mapping)
            else:
                try:
                    self.logger.info('Updating mapping of index "%s" ...' % self.elasticsearch_index)
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
                except elasticsearch.exceptions.ConnectionError as err:
                    self.logger.error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
                    exit(1)
                except elasticsearch.exceptions.BadRequestError as err:
                    self.logger.error('Failed to update index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))

                    self.logger.info('Deleting index "%s"...' % self.elasticsearch_index)
                    self.elasticsearch.indices.delete(index=self.elasticsearch_index)

                    self.logger.info('Recreating index "%s" ...' % self.elasticsearch_index)
                    self.create_index(index_mapping)
                except Exception as err:
                    self.logger.error('Failed to update index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))
                    exit(1)
        else:
            self.logger.info('Creating index "%s" ...' % self.elasticsearch_index)
            self.create_index(index_mapping)

    def create_index(self, index_mapping):
        index_settings = {
            "analysis": {
                "tokenizer": {
                    self.elasticsearch_tokenizer: {
                        "type": "simple_pattern",
                        "pattern": "[a-zA-Z0-9]+"
                    }
                },
                "analyzer": {
                    "default": {
                        "tokenizer": self.elasticsearch_tokenizer,
                        "filter": [
                            "lowercase",
                            "asciifolding"
                        ]
                    }
                }
            }
        }
        try:
            if self.elasticsearch_lib_version == 7:
                self.elasticsearch.indices.create(
                    index=self.elasticsearch_index,
                    body=index_mapping,
                    settings=index_settings
                )
            elif self.elasticsearch_lib_version == 8:
                self.elasticsearch.indices.create(
                    index=self.elasticsearch_index,
                    mappings=index_mapping['mappings'],
                    settings=index_settings
                )
        except elasticsearch.exceptions.ConnectionError as err:
            self.logger.error('Failed to connect to elasticsearch at "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)
        except Exception as err:
            self.logger.error('Failed to create index at elasticsearch "%s": %s' % (self.elasticsearch_url, str(err)))
            exit(1)

    def refresh_index(self):
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
