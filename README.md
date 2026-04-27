# change-pdf

A web app to find a word inside any PDF file and **redact** it (black box), **replace** it with custom text, or **highlight** it — then download the edited PDF instantly.

## Features

- **Redact** — covers the word with a solid black box (permanently removes it visually)
- **Replace** — swaps every occurrence with your own text
- **Highlight** — adds a yellow highlight annotation over the word
- **Count only** — scans the PDF and reports how many times the word appears per page, without modifying the file
- Drag-and-drop PDF upload
- Case-sensitive search toggle
- Shows total occurrences found
- Auto-downloads the edited PDF

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | [FastAPI](https://fastapi.tiangolo.com/) |
| PDF processing | [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/) |
| Server | [Uvicorn](https://www.uvicorn.org/) |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| Frontend | Vanilla HTML/CSS/JS (no build step) |

## Getting Started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed

### Install & Run

```bash
git clone git@github.com:baxromov/change-pdf.git
cd change-pdf

# Install dependencies
uv sync

# Start the server
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** in your browser.

## API Endpoints

### `POST /process`
Upload a PDF and process every occurrence of the target word.

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | PDF file |
| `word` | string | Word to search for |
| `action` | string | `redact`, `replace`, or `highlight` |
| `replacement` | string | Replacement text (only used when action is `replace`) |
| `case_sensitive` | bool | Default `false` |

Returns the edited PDF as a file download. The response header `X-Words-Found` contains the count of replaced occurrences.

### `POST /count`
Count occurrences without modifying the PDF.

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | PDF file |
| `word` | string | Word to search for |

```json
{
  "total": 5,
  "word": "confidential",
  "pages": [
    { "page": 1, "count": 3 },
    { "page": 4, "count": 2 }
  ]
}
```

## Project Structure

```
change-pdf/
├── main.py                  # FastAPI app + PDF processing logic
├── migrate_collection.py    # Qdrant collection migration script
├── static/
│   └── index.html           # Frontend UI
├── pyproject.toml           # Project metadata & dependencies
├── .env.example             # Qdrant credentials template
└── uv.lock                  # Locked dependency versions
```

---

## Qdrant Collection Migration

`migrate_collection.py` duplicates the `hr-assistent` Qdrant collection into a new `hr-assistant-v2` collection, removing all Ipoteka-Bank / OTP Group brand references from the `page_content` payload field. The original collection is never modified.

### Setup

```bash
cp .env.example .env
# Edit .env and set your QDRANT_URL and QDRANT_API_KEY
```

### Run

```bash
python migrate_collection.py
```

### What it does

- Connects to remote Qdrant using credentials from `.env`
- Reads all points from `hr-assistent` (paginated)
- Strips these patterns from `page_content` (case-insensitive):
  - `Ipoteka-Bank` / `Ipoteka Bank`
  - `Ипотека-Банк` (Cyrillic)
  - `ОАО «Ипотека-Банк»` (legal name)
  - `OTP Group`
- Creates `hr-assistant-v2` with the cleaned data
- Prints a summary: total points copied and how many had text removed
- If `hr-assistant-v2` already exists, prompts before overwriting
