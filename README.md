# Adras — Autonomous Data Analyst API ⚡

Adras is a completetly autonomous multimodal data analyst agent that can scrape data from html websites, csv files, and external buckets to solve complex natural language data analysis queries.

FastAPI service that turns natural-language analysis requests into executable Python, runs them, and returns structured results.


## Demo Video


🚀 **Check out the YouTube Demo!** 👉 [Watch the demo on YouTube](https://youtu.be/eHAeP_hQNOw)


## Features

- Single POST endpoint that accepts a questions.txt plus optional assets.
- Auto-routes to the right lane (web/file/external) and iterates until a valid JSON answer is produced.
- Robust JSON extraction and fail-proof fallback to preserve output format.
- Per-request sandbox workspace under temp/<uuid> with automatic cleanup.

## Repository structure

```
.env
.gitignore
LICENSE
requirements.txt
main.py
splitter.py
web_pipeline.py
file_pipeline.py
external_pipeline.py
scraper.py
.github/
  workflows/
    main_adras.yml
temp/                       # per-request working directory (ephemeral)
```

Key files:
- API: [main.py](main.py)
- Lane classifier: [`splitter.classify_from_req_id`](splitter.py)
- Web lane: [`web_pipeline.web_pipeline`](web_pipeline.py)
- File lane: [`file_pipeline.file_pipeline`](file_pipeline.py)
- External-data lane: [`external_pipeline.external_pipeline`](external_pipeline.py)
- Table metadata scraper (web helper): [`scraper.scrape`](scraper.py)

## Requirements

- Python 3.12
- GROQ_API_KEY set in your environment
- System libs for pandas/lxml as needed
- Python deps: [requirements.txt](requirements.txt)

## Quick start

1) Install dependencies
```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Configure environment
```sh
export GROQ_API_KEY=your_groq_key
```

3) Run the API
```sh
uvicorn main:app --reload --port 8000
```

4) Sanity check
```sh
curl http://localhost:8000/health
# {"status":"ok"}
```

## API

Base URL: /

- GET `/` — service banner
- GET `/health` — health probe
- POST `/api/` — multipart/form-data

Request contract:
- Required: questions.txt (field name or filename must be exactly questions.txt). Content: the natural-language task.
- Optional:
  - Data files: .csv, .xls, .xlsx (file lane)
  - Images: .png, .jpg, .jpeg (saved; not always used)

Example:
```sh
curl -X POST http://localhost:8000/api/ \
  -F "questions.txt=@./examples/questions.txt" \
  -F "dataset=@./examples/sales.csv"
```

Response:
- JSON produced by the selected pipeline.
- If JSON is not cleanly produced, the system attempts robust extraction; if that fails, a format-preserving fallback is returned.

## How it works

1) Staging
   - Writes uploads to temp/<uuid>/ with subfolders:
     - files/ for data files
     - images/ for images
   - Cleanup scheduled in background: [`main.cleanup_temp_dir`](main.py)

2) Classification
   - [`splitter.classify_from_req_id`](splitter.py) predicts: web, file, mixed, external_data, or other using Groq model openai/gpt-oss-120b.
   - Routing (in [main.py](main.py)):
     - file* → [`file_pipeline.file_pipeline`](file_pipeline.py)
     - web* → [`web_pipeline.web_pipeline`](web_pipeline.py)
     - external* → [`external_pipeline.external_pipeline`](external_pipeline.py)
     - other → fail-proof fallback

### File lane

- Entry: [`file_pipeline.file_pipeline`](file_pipeline.py)
- CSV probing: [`file_pipeline.probe_csv_structure`](file_pipeline.py) for metadata (columns, dtypes, sample rows).
- Models:
  - Generator: openai/gpt-oss-120b
  - Checker: openai/gpt-oss-20b
- Executes generated code inside the request dir: [`file_pipeline.run_code_in_reqdir`](file_pipeline.py)
- Output handling:
  - Base64 summarization: [`file_pipeline.summarize_base64_in_text`](file_pipeline.py)
  - JSON extraction: [`file_pipeline.extract_json_from_text`](file_pipeline.py)
- Up to 10 iterations, then fail-proof fallback if needed.

### Web lane

- Entry: [`web_pipeline.web_pipeline`](web_pipeline.py)
- URL detection: [`web_pipeline.extract_urls`](web_pipeline.py)
- Minimal table metadata via [`scraper.scrape`](scraper.py) (first table only; pandas.read_html).
- Models:
  - Generator: llama-3.3-70b-versatile
  - Checker: meta-llama/llama-4-scout-17b-16e-instruct
- Helpers:
  - [`web_pipeline.extract_python_code`](web_pipeline.py)
  - [`web_pipeline.extract_json`](web_pipeline.py)
  - [`web_pipeline.replace_base64`](web_pipeline.py)
  - Fallback: [`web_pipeline.fail_proof`](web_pipeline.py), [`web_pipeline.stub_response_former`](web_pipeline.py)

### External-data lane

- Entry: [`external_pipeline.external_pipeline`](external_pipeline.py)
- Focused on APIs/datasets mentioned in the question (no scraping or local files).
- Models: same generator; checker = meta-llama/llama-4-scout-17b-16e-instruct
- Output cleanup: [`external_pipeline.clean_json`](external_pipeline.py), JSON extraction + ast.literal_eval.

### Fail-proofing

If clean JSON is missing:
- [`web_pipeline.fail_proof`](web_pipeline.py) tries robust extraction.
- [`web_pipeline.stub_response_former`](web_pipeline.py) produces a format-correct fallback.

Note: Guarantees format, not correctness.

## Models and prompting

- Classification: openai/gpt-oss-120b ([`splitter.classify_from_req_id`](splitter.py))
- Generation: llama-3.3-70b-versatile
- Checkers: openai/gpt-oss-20b (file), meta-llama/llama-4-scout-17b-16e-instruct (web/external)
- All via Groq SDK (key: GROQ_API_KEY)

## Temp workspace

- temp/<uuid>/ contains:
  - questions.txt
  - files/*
  - images/*
- Cleaned up post-response: [`main.cleanup_temp_dir`](main.py)

## Deployment (GitHub Actions → Azure Web App)

- Workflow: [.github/workflows/main_adras.yml](.github/workflows/main_adras.yml)
  - Build on ubuntu-latest, Python 3.12
  - Install deps, upload artifact, deploy to Azure Web App Adras
- Configure GROQ_API_KEY in App Service settings
- Ensure federated credentials secrets are set

## Configuration

- .env (or env vars):
  - GROQ_API_KEY — required
- CORS: open to all origins in [main.py](main.py)
- Timeouts:
  - Web code: 120s ([`web_pipeline.run_code`](web_pipeline.py))
  - Scraper: 30s ([`scraper.run_code`](scraper.py))
  - File lane: 180s per step ([`file_pipeline.run_code_in_reqdir`](file_pipeline.py))

## Security notes

- Executes model-generated Python. Use sandboxing and avoid exposing secrets.
- Uploaded content removed after response (best-effort).
- Base64-heavy outputs are summarized before being sent back to models.

## Troubleshooting

- 400 “questions.txt is required”: ensure the field/filename is exactly questions.txt.
- Missing GROQ_API_KEY: set it in .env or the environment.
- lxml build issues: install libxml2/libxslt or use wheels.
- JSON parsing failures: pipelines will fallback; ensure the question requests a machine-parseable output.

## License

MIT — see [LICENSE](LICENSE)