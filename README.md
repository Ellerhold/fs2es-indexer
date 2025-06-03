# FileSystem To ElasticSearch Indexer

This tool indexes your files and directories into an elastic search index and prepares them for searching 
via macOS Spotlight search in a samba file server.

## Installation

Install the dependencies:
- Python3 (Debian package: `python3`)
- PyYAML (Debian package: `python3-yaml`)
- Python-ElasticSearch v8 or higher (Use a venv - see below)
- a running ElasticSearch instance v8 or higher (see [ElasticSearch installation](https://www.elastic.co/guide/en/elasticsearch/reference/current/install-elasticsearch.html#install-elasticsearch))

And download the content of this repo to a directory (e. g. `/opt/fs2es-indexer`).

### Installation in a virtual env

Debian does not like it if you use `pip install <anything>` because you'd pollute the standard python environment with 
your dependencies.

They recommend this (cleaner) way:

```bash
# Install the venv module (if you dont have it already)
apt install python3-venv

# Create a virtual env for our dependencies, but enable the access to the system packages
python3 -m venv --system-site-packages /opt/fs2es-indexer/

# Install our dependencies in this virtual env only
/opt/fs2es-indexer/bin/pip3 install 'elasticsearch>=8,<9'

# Optional if you want to use the fanotify watcher
# You may need the 'python3-dev' to compile it successfully.
/opt/fs2es-indexer/bin/pip3 install 'pyfanotify'

# Use our new virtual env to run the indexer
/opt/fs2es-indexer/bin/python3 /opt/fs2es-indexer/fs2es-indexer
```

### Configuration

Copy the `config.dist.yml` to `/etc/fs2es-indexer/config.yml` and tweak it to your hearts content!

You have to configure which directories should be indexed and the URL & credentials for your ElasticSearch instance.

### Running it

```bash
# Index the configured directories once
/opt/fs2es-indexer/fs2es-indexer index

# Index the configured directories, wait for the specified amount of time and index again
# Continously!
/opt/fs2es-indexer/fs2es-indexer daemon

# Deletes all documents in the elasticsearch index
/opt/fs2es-indexer/fs2es-indexer clear

# You can test the Spotlight search with this indexer!

# Shows the first 100 elasticsearch documents
/opt/fs2es-indexer/fs2es-indexer search --search-path /srv/samba

# Searches elasticsearch documents with a match on all attributes:
/opt/fs2es-indexer/fs2es-indexer search --search-path /srv/samba --search-term "my-doc.pdf"

# Searches elasticsearch documents with a match on the filename:
/opt/fs2es-indexer/fs2es-indexer search --search-path /srv/samba --search-filename "my-doc.pdf"

# Displays some help texts
/opt/fs2es-indexer/fs2es-indexer --help
```

### SystemD service

You can use the `/opt/fs2es-indexer/fs2es-indexer.service` in order to register the daemon-mode as a SystemD service. 

## Configuration of Samba
Add this to your `[global]` section in your `smb.conf`:
```ini
spotlight backend = elasticsearch
elasticsearch:address = 127.0.0.1
elasticsearch:port = 9200
elasticsearch:ignore unknown attribute = yes
elasticsearch:ignore unknown type = yes
```

If your elasticsearch instance is not on the local machine, use the correct IP address above.

The last 2 options are entirely optional but sometimes MacOS sends queries with some weird attributes and types. The 
default behavior is to fail the whole search then.
If you set both to "yes" samba will use what it can from the query and tries the search regardless. So you may get 
invalid results which you seemingly excluded.

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

Make sure your search term is the start of a word in the file name. E.g. searching for "Test" should find files
named "Test123.pdf", "Testing-yesterday.doc" and "This_Is_My_Test.xml" (since 0.8.0) but *not* the file named "notestingdone.pdf".

fs2es-indexer prior to 0.8.0 used the [standard tokenizer of elasticsearch](https://www.elastic.co/guide/en/elasticsearch/reference/current/analysis-standard-tokenizer.html) 
which does not recognize certain symbols as word-boundaries, e. g. the underscore "_" is not recognized as a word boundary. 
So the file "This_Is_My_Test.xml" should only be found if fs2es-indexer is installed in 0.8.0+.

This constraint comes from the way samba (at least since 4.15+) creates the ES query and fs2es-indexer mimicks this 
behavior as close as possible. There is currently no way to change this in samba (and therefor impossible in 
fs2es-indexer too).

### 4. Does Server's mdsearch find the files?

Try this on the server first:
```bash
# Searches in all attributes:
mdsearch localhost "<Share>" '*=="<Search Term>"' -U "<User>"

# Searches just the filename:
mdsearch localhost "<Share>" 'kMDItemFSName=="<Search Term>"' -U "<User>"
```

Does this yield results?

### 5. Does your Mac uses the correct search index?

Go on your macOS client and connect to the samba share ( = mounting the share in /Volumes/my-share).

Start a terminal and execute

```bash
mdutil -s /Volumes/my-share
```

Does it say "Server search enabled"? 

If not: 
- Are you using Samba 4.12.0 or later?
- Was Samba compiled with spotlight support (default for debian packages)? 
- Is elasticsearch enabled in your smb.conf (on the server)? 

### 6. Does your Mac's mdfind finds anything?

Start a terminal on your Mac-Client and execute
```bash
mdfind -onlyin /Volumes/my-share <search-term>
```

Use the same search-term as in step 3!

If no output is produced: wait 5 seconds and try again.

If this fails: check your samba-logs on the server. Any entries with "rpc_server", "mds" or "mdssvc" in it?

### 7. Does your Mac's Finder find anything?

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

## How can I uninstall fs2es-indexer?

You can uninstall the indexer with pip:

```bash
# The indexer itself:
python3 -m pip uninstall fs2es-indexer

# You can check whats installed via
python3 -m pip list
# or
pip3 list

# Its dependencies
python3 -m pip uninstall elasticsearch elastic-transport certifi urllib3 PyYAML

# This may fail for version < 0.5 (where we switched to pip)
# Look into these folders:
ls -lAh /usr/local/lib/python3.9/dist-packages
ls -lAh /usr/lib/python3/dist-packages
rm /usr/bin/fs2es-indexer

# If you delete anything there and it's still listed in `pip3 list`, then you have to edit these files:
vi /usr/local/lib/python3.9/dist-packages/easy-install.pth
vi /usr/lib/python3/dist-packages/easy-install.pth

# After updating from < 0.5 to 0.5+ you may have to cleanup your /opt/fs2es-indexer
rm -Rf /opt/fs2es-indexer/build /opt/fs2es-indexer/dist /opt/fs2es-indexer/files.txt /opt/fs2es-indexer/fs2es_indexer.egg-info
```

Please make sure that all the dependencies are ONLY used for the indexer and not for any other program.

## Advanced: Switch back to elasticsearch v7

You have to install the elasticsearch-python library in version 7, e.g. via pip
```
python3 -m pip install 'elasticsearch>=7,<8'
```

And configure this in your `config.yml`:
```yaml
elasticsearch:
  library_version: 7
```

This **should** work!

## Advanced: How does the daemon mode work?

The daemon mode consists of two different activities:
- indexing
- waiting / watching for filesystem changes

### Indexing runs

Directly after the start of the daemon mode the elastic search index is setup and an indexing run is started.

First elasticsearch is queried and all document IDs are retrieved and saved in RAM. These document IDs are unique and 
derived from the path of the file or directory. 

After that all directories are crawled and new elasticsearch documents are created when no existing document ID can be 
found. If an existing ID was not found during the crawl, it's presumed that the file or dir on this path was deleted and the 
document will be purged from elasticsearch too. 

After this indexing the waiting period begins.

### Waiting period: No changes watcher configured

If the audit log monitoring is disabled: nothing happens except waiting.
Make to sure to strike a balance between server load (indexing runs take a toll!) and uptodateness of the index.

### Waiting period: WITH samba audit log monitoring

This new feature in version 0.6.0 can radically enhance your spotlight search experience!

Normally during the configured `wait_time` no updates are written to elasticsearch. So if an indexing run is done and 
someone deletes, renames or creates a file this change will be picked up during the next run after the `wait_time` is over.

Version 0.6.0 introduces the monitoring of the samba audit log. If setup correctly, samba writes all changes into a separate file.
During the wait time, this file is parsed and changes (creates, deletes and renames) are pushed to elasticsearch.
So changes are visible in the spotlight search (and elasticsearch) almost immediatly after doing them.

#### How to setup the samba audit log
Add these lines to your `/etc/samba/smb.conf`:
```
[global]
    # Add your current vfs objects after this 
    vfs objects = full_audit ...
    full_audit:success = renameat unlinkat mkdirat
    
    # These may be necessary too:
    full_audit:facility = local5
    full_audit:priority = notice
```

Add the `rsyslog-smbd-audit.conf` to your syslog configuration.
In debian: copy it into `/etc/rsyslog.d/` and `systemctl restart rsyslog`.
This will redirect all log entries to `/var/log/samba/audit.log`.

This log file may need to be created manually:
```bash
mkdir -p /var/log/samba
touch /var/log/samba/audit.log
chown syslog:adm /var/log/samba/audit.log
```

Add a logrotate configuration for this file, so it gets cleaned up.
In debian: copy the `samba-audit-logrotate.conf` to `/etc/logrotate.d/samba-auditlog`.
fs2es-indexer handles log rotation (either with "copytruncate" or without) gracefully since 0.10.0.

Currently, there is no good method to log the creation of files. There is "openat" that logs all read 
and write operations. Sadly we cant filter for the "w" flag of this operation directly in Samba, so all "openat" 
operations would be logged. This will generate a massive amount of log traffic on even a moderatly used fileserver 
(gigabytes of text!).

### Waiting period: WITH fanotify to look for changes

This new feature in version 0.11.0 is a better alternative to the samba audit.log monitoring.

Instead of parsing the samba audit.log this watcher uses [fanotify](https://man7.org/linux/man-pages/man7/fanotify.7.html) (a kernel feature since linux 5.1)
to detect changes in the directories and update the elasticsearch index. 

The big advantage over the audit.log monitoring is, that now we get all dir/file creations reliably without blowing up the log file. 
In fact you can disable the audit logging entirely and save on IOPS / space and greatly reduce the server load this indexer produces.
Additionally because its a linux kernel feature and not samba-related it can detect ALL changes, even those that are done by server-local scripts, ...

Your kernel and filesystem must support fanotify and the indexer must run as `root`! I tested it successfully with Debian 12, ext4 and OpenZFS. 

You need to install the python package [pyfanotify](https://github.com/baskiton/pyfanotify) to set `use_fanotify` to `True` in your `config.yml`.
For installation via pip under Debian I needed to install `python3-dev` too, because the C-part of this package cant be compiled otherwise.

You could set the `wait_time` in your `config.yml` to something really high (like 30m) to further reduce the load of the indexer on your system.

And of course: if you used the audit.log watcher before, you can now remove all config for it from your samba, rsyslog etc...

## Advanced: Which fields are displayed in the finder result page?

The basic mapping of elasticsearch to spotlight results can be found here: [elasticsearch_mappings.json](https://gitlab.com/samba-team/samba/-/blob/master/source3/rpc_server/mdssvc/elasticsearch_mappings.json)

I'm currently unsure WHICH fields are really queried, mapped and returned to spotlight.
In Samba versions prior to 4.21.4 (and backported to 4.20.8):
- "filesize" is not returned, so it's empty in the result page.
- "last_modified" is not returned, but the finder displays a date. Sometimes this date is well into the future (+ 5 - 6 years).

Samba 4.21.4 & 4.20.8 changes this behavior:
filesize, birth date and last modified date are now returned by samba and will be correctly displayed. The "type" column is still empty though.
Thanks to Ralph Böhme of SerNet for implementing this feature request!
