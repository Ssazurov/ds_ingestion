## 2026-09-13 -- ingestion request timeout handling

- `GarClient.ingest_document()` converts `httpx.RequestError` (including request
  timeout) into `GarClientError`; adapter records one failed document and keeps
  processing the remaining source documents.
- No automatic retry is used: a timed-out upload may still be processing in
  `gar-core-api`, so retry could create a duplicate document.
- `GAR_REQUEST_TIMEOUT_S` remains configurable and defaults to `660` seconds,
  matching the documented `gar-docling-intake` subprocess limit plus margin.
