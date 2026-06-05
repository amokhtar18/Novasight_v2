# Sensitive-data encryption (Phase 5.4)

Columns a dataset tags **sensitive** are encrypted at rest in the lake and only
decrypted on access-controlled read paths. Everything is config-driven (golden
rule 1) and tenant-scoped.

## Pieces

| Concern | Module | Responsibility |
|---------|--------|----------------|
| Key authority | [`app/core/crypto.py`](../backend/app/core/crypto.py) | `KmsProvider` protocol + `LocalAesGcmProvider`; value encrypt/decrypt; `build_kms_provider`. |
| Tags | [`app/models/dataset.py`](../backend/app/models/dataset.py) `sensitive_columns` | Per-dataset list of logical column names tagged sensitive. |
| Encrypt on ingest | [`app/ingestion/encryption.py`](../backend/app/ingestion/encryption.py) | Replace tagged Arrow columns with ciphertext before the Iceberg write. |
| Access policy | [`app/core/sensitive.py`](../backend/app/core/sensitive.py) | `may_view_sensitive` (role check) + `apply_to_rows` (mask or reveal). |
| Roles | [`app/core/security.py`](../backend/app/core/security.py) `Principal.roles` | Roles parsed from the configured JWT claim. |
| At-rest (object store) | [`app/core/object_store.py`](../backend/app/core/object_store.py) | Requests server-side encryption (SSE) on every write when configured. |

## Lifecycle

1. **Tag** — a dataset's `sensitive_columns` lists the columns to protect.
2. **Ingest** — the CSV→Iceberg pipeline encrypts those columns cell-by-cell
   (AES-256-GCM via the configured provider) before writing, so they land as
   opaque base64 tokens (`enc:v1:…`). The raw upload object is additionally written
   with object-store SSE when `OBJECT_STORE__SERVER_SIDE_ENCRYPTION` is set.
3. **Read** — serving (ClickHouse over the Iceberg table) returns the ciphertext.
   The application then either:
   - **reveals** (decrypts) for an interactive principal holding the configured
     `ENCRYPTION__SENSITIVE_VIEW_ROLE`, or
   - **masks** (`***`) for everyone else — unauthorized callers and background jobs.
4. **Reports** — scheduled reports run with no interactive principal, so sensitive
   columns are **always masked**; a report can never become a back door around
   access control.

## Access control

A principal sees decrypted values only if its JWT roles claim
(`AUTH__ROLES_CLAIM`, default `roles`) contains `ENCRYPTION__SENSITIVE_VIEW_ROLE`
(default `sensitive_viewer`). With encryption unconfigured, nothing is ever
revealed (fail closed).

## Configuration

| Var | Meaning |
|-----|---------|
| `ENCRYPTION__PROVIDER` | `local` (symmetric key in settings) or a future KMS provider. |
| `ENCRYPTION__KEY` | Local provider only: base64-encoded 32-byte AES key (a secret). |
| `ENCRYPTION__SENSITIVE_VIEW_ROLE` | Role required to see decrypted values. |
| `AUTH__ROLES_CLAIM` | JWT claim carrying the principal's roles. |
| `OBJECT_STORE__SERVER_SIDE_ENCRYPTION` | SSE algorithm requested on writes (`AES256`, `aws:kms`). |

The `ENCRYPTION__*` group is optional and only required once a dataset actually
tags a column sensitive; the ingestion/serving paths fail closed with a clear
error if it is missing. See [`.env.example`](../backend/.env.example).

## Guarantees (and where they're tested)

- **Encrypted at rest** — `test_ingestion_encryption.py`: the Arrow table written
  to Iceberg has tagged columns as ciphertext that round-trips; untagged columns
  stay plaintext.
- **Decryption is access-controlled** — `test_datasets.py`: the query endpoint
  masks for a tokenless/role-less caller and reveals only with the role;
  `test_sensitive.py` covers the policy directly.
- **No plaintext in logs** — `test_ingestion_encryption.py` asserts plaintext
  values never appear in emitted log records (the redaction filter in
  `app/core/logging.py` additionally scrubs known sensitive keys).
