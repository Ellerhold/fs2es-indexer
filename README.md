# FileSystem To Elastic Search Indexer

This tool indexes your directories into an elastic search index and prepares them for searching via Mac OS Spotlight 
search in a samba file server.

## Dependencies:
- YAML (`python3-yaml` in Debian)
- Python-ElasticSearch ([python-elasticsearch](https://elasticsearch-py.readthedocs.io/))

## Installation

Grab the source code and call `python3 setup.py install` (add `--install-layout=deb` if you're on debian).

## Configuration

Copy the `config.dist.yml` to `/etc/fs2es-indexer/config.yml` and tweak it to your hearts content:

You have to configure the directories that should be indexed and the URL & credentials for the Elastic Search database.

Call the `fs2es-indexer` to start indexing your configured directories!

Type `fs2es-indexer --help` to get some help.

## Optional

If you want to start fresh you can call `fs2es-indexer clear` to clear the ES index. No indexing will happen.

## How does it work?

First the current timestamp is saved as a marker to flag new and updated documents as uptodate.

It goes through all of your directories and indexes them into elastic search documents, these documents get a "time" 
attribute that has the value of the saved marker.

After that, all documents with a "time" value of less than the saved marker will be deleted. 
This ensures that documents of old files in the filesystem will be deleted from the elasticsearch index.
