# FileSystem To Elastic Search Indexer Changelog

## 0.3.2
- add `file.filesize` to elasticsearch index, so that Spotlight can see it

## 0.3.1
- remove positional calls to the ElasticSearch lib methods to make it compatible with lib version 8.0

## 0.3.0
- added config for exclusions (e. g. MacOS Index files or the trash folder)

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