# FileSystem To ElasticSearch Indexer

This tool indexes your files and directories into an elastic search index and prepares them for searching 
via macOS Spotlight search in a samba file server.

## Dependencies:
- Python3 (Debian package: `python3`)
- Poetry (see [Poetry Installation](https://python-poetry.org/docs/#installation))
- a running ElasticSearch instance v8 or higher (see [ElasticSearch installation](https://www.elastic.co/guide/en/elasticsearch/reference/current/install-elasticsearch.html#install-elasticsearch))

## Installation

Grab the source code and call `poetry install`.

### Configuration

Copy the `config.dist.yml` to `/etc/fs2es-indexer/config.yml` and tweak it to your hearts content!

You have to configure which directories should be indexed and the URL & credentials for your ElasticSearch instance.

### Running it

```bash
# When using a virtualenv created by Poetry:
poetry run fs2es-indexer

# Index the configured directories once
fs2es-indexer index

# Index the configured directories, wait for the specified amount of time and index again
# Continously!
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

You can use the `fs2es-indexer.service` in order to register the daemon-mode as a SystemD service. 

## Configuration of Samba
Add this to your `[global]` section in your `smb.conf`:
```ini
spotlight backend = elasticsearch
elasticsearch:address = 127.0.0.1
elasticsearch:port = 9200
```

If your elasticsearch instance is not on the local machine, use the correct IP address above.

## User authentication

In elasticsearch v8 the user authentication was made mandatory for elasticsearch.

### 1. Add the roles

Add the content of `role.yml` to the `roles.yml` of your elasticsearch (e. g. in Debian: `/etc/elasticsearch/roles.yml`).

Unknown if needed: restart your elasticsearch (e. g. in Debian: `systemctl restart elasticsearch`).

### 2. Add the user

Navigate to the installation directory of elasticsearch (e. g. in Debian: `/usr/share/elasticsearch`).

```bash
# Create a new user
bin/elasticsearch-users useradd fs2es-indexer
# Use a good password!

# Add the new role to it
bin/elasticsearch-users roles -a fs2es-indexer fs2es-indexer
```

### 3. Configure fs2es-indexer

Edit your `/etc/fs2es-indexer/config.yml` and insert your values for `user` and `password` in `elasticsearch`. 
See the template `config.dist.yml` for an example.

### 4. Configure ElasticSearch

Samba as of 4.15.6 can't use user authentication yet. 
There is a [pull request](https://gitlab.com/samba-team/samba/-/merge_requests/1847) to add this feature, but it's not merged (yet).

That's why we have to enable the anonymous access to ES with a role that can read all indexed files.

Add this to your `/etc/elasticsearch/elasticsearch.yml`:
```yaml
# Allow access without user credentials for Samba 4.15
# See https://www.elastic.co/guide/en/elasticsearch/reference/current/anonymous-access.html
xpack.security.authc:
  anonymous:
    username:        anonymous_user
    roles:           fs2es-indexer-ro
    authz_exception: true
```

## Debugging the search

The whole macOS finder -> Spotlight -> Samba -> ES system is complex and a number of things can go wrong.

Use this guideline to determine where the problem might be.

### 1. Is Elasticsearch running correctly?

Is elasticsearch running / accepting any connections? In debian run `systemctl status elasticsearch`.
Additionally, look through the logs found in `/var/log/elasticsearch`.

### 2. Is fs2es-indexer running correctly?

Did the tool correctly index your directories? Look through the output of `fs2es-indexer index` or `daemon`. 

Check your configuration in `/etc/fs2es-indexer/config.yml`, use the `config.dist.yml` as base.

### 3. Does the indexer find the files you're looking for?

Try to find some files with `fs2es-indexer search --search-path <Local Path> --search-term <Term>`.

If nothing is found: Did the indexer run correctly? Are there any auth or connection problem? 
Check your ES and indexer logs!

Make sure your search term is the start of a word in the file name. E.g. searching for "Test" could find files
named "Test123.pdf", "Testing-yesterday.doc" and "This_Is_My_Test.xml" but *not* the file named "notestingdone.pdf".

This constraint comes from the way samba (4.15) creates the ES query and fs2es-indexer mimicks this behavior as close 
as possible. There is currently no way to change this in samba (and therefor impossible in fs2es-indexer too).

### 4. Does your Mac uses the correct search index?

Go on your macOS client and connect to the samba share ( = mounting the share in /Volumes/my-share).

Start a terminal and execute

```bash
mdutil -s /Volumes/my-share
```

Does it say "Server search enabled"? 

If not: 
- is elasticsearch enabled in your smb.conf (on the server)? 
- Was Samba compiled with spotlight support? 
- Are you using Samba 4.12.0 or later?

### 5. Does your Mac's mdfind finds anything?

Start a terminal on your Mac-Client and execute
```bash
mdfind -onlyin /Volumes/my-share <search-term>
```

Use the same search-term as in step 3!

If no output is produced: wait 5 seconds and try again.

If this fails: check your samba-logs on the server. Any entries with "rpc_server", "mds" or "mdssvc" in it?

### 6. Does your Mac's Finder find anything?

Start the Finder on your Mac and navigate to the samba share. Use the search field at the top right and type in your 
search term.

Wait for the spinner to finish. If no files are returned and Step 5 succeeded: IDK (srsly).

If your finder hangs then you have a problem with the `.DS_Store` and `DOSATTRIBS` on your server. This can happen 
if you rsync files from an old macOS server to the new linux samba server.

In order to fix this you have to execute these on the samba server:
```bash
find /my-storage-path -type f -name ".DS_Store" -delete
find /my-storage-path -exec setfattr -x user.DOSATTRIB {} \;
```

And add these lines to your [global] section in the smb.conf on the samba server:
```bash
    veto files = /.DS_Store/
    delete veto files = yes
```

You have to restart your Mac-OS client btw, because it crashed and won't be usable otherwise.

## Advanced: Switch to elasticsearch v7

You have to install the elasticsearch-python library in version 7, e.g. via the setup.py
```python
install_requires=[
  'PyYaml',
  'elasticsearch>=7,<8'
]
```

And configure this in your `config.yml`:
```yaml
elasticsearch:
  library_version: 7
```

This **should** work!

## Advanced: How does it work?

First the current timestamp is saved as a marker to flag new and updated documents as uptodate.

It goes through all of your directories and indexes them into elastic search documents, these documents get a "time" 
attribute that has the value of the saved marker.

After that, all documents with a "time" value of less than the saved marker will be deleted. 
This ensures that documents of old files in the filesystem will be deleted from the elasticsearch index.
