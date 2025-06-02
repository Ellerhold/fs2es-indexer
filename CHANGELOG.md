# FileSystem To Elastic Search Indexer Changelog

## 0.11.0
- You can now use fanotify (via pyfanotify) to watch for filesystem changes instead of parsing a custom samba audit.log file
  - This will capture all changes in the filesystem, even those not made by samba
  - See the README.md on how to set up this changes watcher
- Removed the venv stuff from the `DEBIAN/postinst` file, because this should be done during packaging (TODO test it)

## 0.10.0
- Handle log rotation gracefully
- Add a log rotation configuration suggestion
- Add more documentation hints for the audit log monitoring (thanks @hondaspb!) 

## 0.9.1
- Provide a summary for the new action "analyze_index" whether the index must be recreated or not.

## 0.9.0
- Add "lowercase" and "asciifolding" filters to the elasticsearch analyzer to make the search query case insensitive.
  - Example:
    - You have a file named "My_wonderful_Document.pdf" with a capital D on Document.
    - Old behaviour: searching for "document" wouldnt get you any results. You'd have to search for "Document"
    - New behaviour: searching for "document" (in fact any case) will give you the one result.
  - A **full** reindex is necessary because these new filters only run during the index of a document and not after the fact.
    - This will be detected and done automatically.

## 0.8.0
- Change the tokenizer of the elasticsearch index to our own in order to split the filename correctly into tokens. Explanation:
  - During indexing the tokenizer of elasticsearch splits the filename into (multiple) words (called "tokens" here). The normal tokenizer of elasticsearch does not interpret underscore ("_") as a word boundary!
  - The samba spotlight search works at the start of a word: it matches elasticsearch document that have a token starting with the searchterm.
  - Example: 
    - You have a file named "My_wonderful_document.pdf"
    - Old behaviour:
      - Elasticsearch splits this filename into 2 tokens: "My_wonderful_document" and "pdf"
      - Searching for "wonderful" wouldn't result in any results, because no token starts with "wonderful"!
    - New Behaviour:
      - Elasticsearch splits this filename into 4 tokens: "My", "wonderful", "document" and "pdf"
      - Searching for "wonderful" would return the file, because its 2nd token starts with "wonderful".
  - A **full** reindex is necessary because the tokenizer only runs during the index of a document and not after the fact.
    - This will be detected and done automatically.

## 0.7.1
- add "--system-site-packages" to the creation of the venv to enable the access to the system packages (e. g. yaml)

## 0.7.0
- Switch to installation in a virtual env
  - Changes in the debian packaging scripts and README only. No changes in functionality

## 0.6.0
- Major rewrite of the indexer!
- Instead of indexing all paths each time to elasticsearch (which takes a lot of time), the indexer will now retrieve 
which paths are already in ES and only add new ones and remove deleted ones.
- This will massivly speed up indexing runs (from ~ 20 min to ~ 1 min for 2 mio paths)
- Sadly the indexed paths need to be saved in the indexer (~ 500 MiB RAM usaged for 2 mio paths)
- Removed the ability to add more metadata into ES (like filesize and last_modified), because
  - they are unused by Samba, 
  - they slow down the indexer 
  - and are incompatible with the aforementioned indexing algorithm. 
- Changed some mapping for the elasticsearch index. It will be automatically recreated if its incompatible.
- New feature: monitor the samba audit log during the wait_time!
  - See README.md for more information
- Add `-v` or `--verbose` to a CLI call to get more information. 

## 0.5.0
- Instead of using the setuptools we're now using pip to install the dependencies
  - See README.md for more info.

## 0.4.9
- revert change from 0.4.7: the format for "time" is once again "long"
- report how long the bulk import into elasticsearch took
- fields "last_modified" and "filesize" are not used yet by Samba
  - You disable indexing them via setting `elasticsearch.add_additional_fields` to `false` (the default)
  - Enabling this has a non-zero performance impact and is (currently) not useful

## 0.4.8
- fix error in "/opt/fs2es-indexer/es-index-mapping.json"

## 0.4.7
- Put the elasticsearch index mapping into an extra file: "/opt/fs2es-indexer/es-index-mapping.json"
  - This path is configurable in the config.yml via the `elasticsearch.index_mapping` key
- Change the "time" flag to an unsigned_long (because epoch can never be negativ) and round it
- Round the mtime of the files

## 0.4.6
- Instead of blowing up the log, it will now dump the documents to a json file in /tmp
  - You can enable / disable this behavior in the config.yml via the `dump_documents_on_error` key (default is false)

## 0.4.5
- Print the documents if the indexing into elasticsearch failed

## 0.4.4
- Output the "objects indexed" count with a space as thousands separator

## 0.4.3
- Add the last modified date to the index for samba / finder to display correct values
- Output the "objects indexed" count with a thousands separator

## 0.4.2
- Add "errors=surrogatepass" for path.encode() to properly treat UTF surrogate characters on some filesystems

## 0.4.1
- Add the files for the debian packaging to this repo

## 0.4.0
- Switch to ES-Lib v8 for ElasticSearch 8.0+
- Add configuration which library version is currently in use
- Fix problems in ES-Lib v8
- Add README.md section on how to enable the user authentication
- Remove "use_ssl" from the ES-constructor and from the configuration

## 0.3.5
- Don't throw an error and abort if a file is deleted during indexing (2nd try)

## 0.3.4
- Don't throw an error and abort if a file is deleted during indexing
- Fix searching with elasticsearch lib 7

## 0.3.3
- add options for connecting to elasticsearch via SSL

## 0.3.2
- add `file.filesize` to elasticsearch index, so that Spotlight can see it
- add `fs2es-indexer search --search-filename "my-document.pdf"` to search the index
- (For the future) add an internal version switch for the elasticsearch library (current version 7 can access ES server 7+)

## 0.3.1
- remove positional calls to the ElasticSearch lib methods to make it compatible with lib version 8.0

## 0.3.0
- added config for exclusions (e.g. macOS Index files or the trash folder)

## 0.2.7
- almost all config options can now be omitted and standard values will be used (exception: "directories")

## 0.2.6
- print duration of whole indexing run

## 0.2.5
- increase default bulk size

## 0.2.4
- add more automatic retries

## 0.2.3
- fix missing variable

## 0.2.2
- Change application flow: first index all directories then clear old documents

## 0.2.1
- add debug messages for connection problems

## 0.2.0
- First public version
