# Removal Plan: AWS Backends (Textract + SageMaker)

**Status**: Draft
**Date**: 2026-03-25

---

## Problem

Quarry supports two backend modes for OCR and embeddings: local (Tesseract/RapidOCR, ONNX) and AWS (Textract, SageMaker). The AWS backends have been tested multiple times and never outperform local. They add complexity (IAM credentials, S3 staging, CloudFormation, region configuration, polling logic, SageMaker endpoint management) with no benefit.

The AWS code represents ~1,100 lines of source, ~550 lines of tests, ~400 lines of infrastructure, ~250 lines of documentation, and 3 heavyweight dependencies (boto3, botocore, s3transfer + stubs). Removing it simplifies the codebase, shrinks the install footprint (~15 MB), and eliminates a class of configuration errors.

## Decision

Remove all AWS backend code, infrastructure, documentation, and dependencies. Quarry is local-only.

---

## Inventory

### Delete entirely

| File | Lines | What it is |
|------|-------|------------|
| `src/quarry/embeddings_sagemaker.py` | 114 | SageMaker embedding backend |
| `src/quarry/ocr_client.py` | 262 | Textract OCR backend (TextractOcrBackend, S3 upload, polling) |
| `tests/test_embeddings_sagemaker.py` | 194 | SageMaker tests |
| `tests/test_ocr_client.py` | 80+ | Textract/S3 tests |
| `infra/manage-stack.sh` | — | CloudFormation deployment script |
| `infra/sagemaker-serverless.yaml` | 115 | CloudFormation template (serverless endpoint) |
| `infra/sagemaker-realtime.yaml` | — | CloudFormation template (realtime endpoint) |
| `infra/sagemaker-inference/code/inference.py` | 63 | Custom SageMaker inference handler |
| `infra/` | — | Delete the entire directory (nothing else lives here) |
| `docs/AWS-SETUP.md` | 132 | AWS onboarding guide |
| `docs/quarry-iam-policy.json` | 35 | IAM policy definition |

### Modify

**`src/quarry/config.py`** — Remove AWS settings fields:
- `aws_access_key_id`, `aws_secret_access_key`, `aws_default_region`
- `s3_bucket`, `sagemaker_endpoint_name`
- `textract_poll_initial`, `textract_poll_max`, `textract_max_wait`, `textract_max_image_bytes`
- `ocr_backend` (hardcode to `"local"` or remove — no longer a choice)
- `embedding_backend` (hardcode to `"onnx"` or remove)
- `embedding_dimension` — keep if used by ONNX backend

**`src/quarry/backends.py`** — Remove `"textract"` and `"sagemaker"` match/case branches. With one implementation per concern, evaluate whether the factory pattern + caching is still justified or should be collapsed to direct instantiation.

**`src/quarry/types.py`** — Remove protocol definitions: `TextractClient`, `S3Client`, `SageMakerRuntimeClient`, `ReadableBody`. Keep `OcrBackend` and `EmbeddingBackend` protocols if backends.py retains the factory pattern.

**`src/quarry/doctor.py`** — Remove `_check_aws_credentials()` and `_check_sagemaker_endpoint()`. Remove `boto3`/`botocore` imports. Keep all local checks.

**`src/quarry/__main__.py`** — Remove `_CLOUD_BACKENDS` frozenset and the cloud-backend worker count branch (lines 620-634). Always use local worker count (1 for CPU-bound).

**`src/quarry/pipeline.py`** — Change `max_bytes=settings.textract_max_image_bytes` to `max_bytes=0` (no limit — local RapidOCR has no API byte constraint). The `_prepare_image_bytes` function itself stays (generic image size reduction).

**`src/quarry/sync.py`** — Remove `botocore.exceptions.ClientError` from the `_recoverable` exception tuple (lines 201-207). Keep the remaining local exceptions (`OSError`, `ValueError`, `RuntimeError`, `TimeoutError`).

**`tests/test_backends.py`** — Remove cloud backend creation tests and mocks. Keep local backend tests and cache tests.

**`pyproject.toml`** — Remove from dependencies:
- `boto3>=1.40.0`
- `boto3-stubs[textract,s3]>=1.40.0`
- `botocore-stubs>=1.40.0`

**`docs/BACKEND-ABSTRACTION.md`** — Simplify. The design doc describes a two-backend abstraction. With one backend per concern, the abstraction layer is simpler. Update to reflect local-only architecture, or delete if the remaining architecture is self-evident from the code.

**`README.md`** — Remove references to AWS/cloud backend acceleration, Textract, SageMaker. Update the feature matrix / backend descriptions.

**`CLAUDE.md`** — Remove "AWS Textract for OCR (user has AWS keys)" from Architecture Decisions.

**`prfaq.tex`** — Check for AWS/Textract/SageMaker references and remove.

**`CHANGELOG.md`** — Add removal entry under `## [Unreleased]`.

### No changes needed

| File | Why |
|------|-----|
| `src/quarry/mcp_server.py` | Uses embedding backend via factory — factory simplification is transparent |
| `src/quarry/http_server.py` | Same — uses factory, no direct AWS code |
| `src/quarry/embeddings.py` | ONNX backend — stays as-is |
| `src/quarry/ocr_local.py` | Local OCR — stays as-is (verify this file exists and is the local implementation) |
| `benchmarks/embed_throughput.py` | Already ONNX-only, no AWS references |
| `Dockerfile` | Downloads model at build time, no AWS SDK in runtime |

---

## Design questions

### Should the backend abstraction survive?

With one OCR backend and one embedding backend, the Protocol + factory pattern adds indirection with no dispatch benefit. Two options:

**Keep the abstraction.** The Protocols (`OcrBackend`, `EmbeddingBackend`) and factory (`get_ocr_backend`, `get_embedding_backend`) survive but each has exactly one implementation. Cost: minor indirection. Benefit: easy to add a new backend later without touching call sites.

**Collapse the abstraction.** Remove `backends.py`. Call sites import the concrete class directly (`from quarry.embeddings import OnnxEmbeddingBackend`). Remove `OcrBackend` and `EmbeddingBackend` protocols from `types.py`. Cost: if a new backend is ever needed, call sites change. Benefit: simpler code, one fewer module, no factory caching.

Trade-off: the factory adds ~85 lines. The protocols add ~30 lines. If a second backend is unlikely (and the user's experience says it is), collapsing is the right call. If quarry might add e.g. an Ollama embedding backend someday, the abstraction pays for itself.

### What about the `ocr_backend` and `embedding_backend` config fields?

Three options:
- **Remove entirely.** No choice = no field. Simplest.
- **Keep as read-only.** Value is always `"local"` / `"onnx"`. `doctor` can report it. Mild cost.
- **Keep with validation.** Raise on any value other than the local default. Tells users who had AWS configured that it's gone.

The third option is the most user-friendly for the transition — a clear error message is better than a silent config key being ignored.

---

## Verification

1. `grep -r "boto3\|textract\|sagemaker\|botocore\|aws_access_key\|aws_secret_access\|aws_default_region\|s3_bucket" src/ tests/ infra/ docs/` — zero hits
2. `python -c "import quarry"` succeeds without boto3 installed
3. `make check` — all tests pass
4. `quarry doctor` — no AWS checks, all local checks pass
5. `quarry ingest` / `quarry find` — work unchanged
6. `pip install .` does not pull boto3
