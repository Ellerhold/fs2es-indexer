# FileSystem To Elastic Search Indexer

This tool indexes your files and directories into an elastic search index and prepares them for searching 
via Mac OS Spotlight search in a samba file server.

## Dependencies:
- Python3 (Debian package: `python3`)
- PyYAML (Debian package: `python3-yaml`)
- SetupTools ([python-setuptools](https://pypi.org/project/setuptools/), Debian package:`python3-setuptools`)
- Python-ElasticSearch ([python-elasticsearch](https://elasticsearch-py.readthedocs.io/en/v7.17.0/))
- a running ElasticSearch instance v7 or higher (see [ElasticSearch installation](https://www.elastic.co/guide/en/elasticsearch/reference/current/install-elasticsearch.html#install-elasticsearch)) 

## Installation

Grab the source code and call `python3 setup.py install` (add `--install-layout=deb` if you're on debian).

## Configuration

Copy the `config.dist.yml` to `/etc/fs2es-indexer/config.yml` and tweak it to your hearts content!

You have to configure which directories should be indexed and the URL & credentials for the Elastic Search database.

```bash
# Index the configured directories once
fs2es-indexer index

# Index the configured directories, wait for the specified amount of time and index again
# Continously 
fs2es-indexer daemon

# Deletes all documents in the elasticsearch index
fs2es-indexer clear

# You can test the Spotlight search with this indexer!

# Shows the first 100 elasticsearch documents
fs2es-indexer search --search-path /srv/samba

# Searches elasticsearch documents with a match on all attributes:
fs2es-indexer search --search-path /srv/samba --search-term "my-doc.pdf"

# Searches elasticsearch documents with a match on the filename:
fs2es-indexer search --search-path /srv/samba --search-filename "my-doc.pdf"

# Displays some help texts
fs2es-indexer --help
```

## How does it work?

First the current timestamp is saved as a marker to flag new and updated documents as uptodate.

It goes through all of your directories and indexes them into elastic search documents, these documents get a "time" 
attribute that has the value of the saved marker.

After that, all documents with a "time" value of less than the saved marker will be deleted. 
This ensures that documents of old files in the filesystem will be deleted from the elasticsearch index.

## User-based authentication

### 1. Add the role

Add the content of `role.yml` to the `roles.yml` of your elasticsearch (e. g. in Debian: `/etc/elasticsearch/roles.yml`).

### 2. Add the user

Navigate to the installation directory of elasticsearch (e. g. in Debian: `/usr/share/elasticsearch`).

```bash
# Create a new user
bin/elasticsearch-users useradd fs2es-indexer
# Use a good password!

# Add the new role to it
bin/elasticsearch-users roles -a fs2es-indexer fs2es-indexer
```

### 3. Configure

Edit your `/etc/fs2es-indexer` and insert your values for `user` and `password`. See the template `config.dist.yml` 
for more information.