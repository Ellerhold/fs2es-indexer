# FileSystem To Elastic Search Indexer Changelog

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