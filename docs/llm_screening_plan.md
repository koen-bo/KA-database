# LLM Screening Step 3

## Summary
- Step 3 executes the screening pipeline from the backend only.
- It uses the existing deterministic Step 1/2 helpers to build the request, then calls OpenAI, validates JSON, and persists the result.
- There is no dashboard button for arbitrary user-triggered screening runs.

## Main Components
- `modules/llm_screening.py`
  - compiles the screening prompt
  - builds the OpenAI request
  - parses and validates structured JSON output
- `screen_documents.py`
  - selects eligible documents
  - skips completed rows by default
  - supports retry/force/dry-run modes
- `modules/database.py`
  - stores screening status, payload, output, model, timestamps, and errors

## Screening Status Model
- `NULL`: never screened
- `pending`: request prepared / running
- `completed`: validated result stored
- `failed`: last attempt failed

## Environment Variables
- `KA_OPENAI_API_KEY`
- `KA_OPENAI_MODEL`
- `KA_OPENAI_BASE_URL`
- `KA_OPENAI_TIMEOUT_SECONDS`
- `KA_OPENAI_MAX_RETRIES`
- `KA_SCREENING_BATCH_SIZE`

## Command Examples
- `python screen_documents.py --limit 5`
- `python screen_documents.py --retry-failed --limit 10`
- `python screen_documents.py --doc-id 123`
- `python screen_documents.py --dry-run --limit 3`
