# Parser provenance

Adapted from `/home/amadeus/Program/ZhihuViewer/zhihu_cli/htmlparse.py` and `mathtex.py`.
Upstream checkout HEAD: `ea8b6bee687b63c044f1f8b699e28b8e60d7b38a` (the local working tree was the supplied reference).
Author: William Marci / Williammarci. MIT license retained in LICENSE and packaging/notices/ZhihuViewer-MIT.txt.

Cosmos supplies a parser-only config.get adapter, removes the Zhihu website URL base, and uses these modules without importing ZhihuViewer networking, credentials, application state or screens. The parser and formula converter are source copies, not a dependency on the original filesystem location. Host integration and pagination live in ../documents.py.
