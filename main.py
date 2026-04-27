import io
import fitz  # PyMuPDF
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="PDF Word Finder & Editor")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/process")
async def process_pdf(
    file: UploadFile = File(...),
    word: str = Form(...),
    action: str = Form(...),          # "redact" or "replace"
    replacement: str = Form(""),
    case_sensitive: bool = Form(False),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    if not word.strip():
        raise HTTPException(status_code=400, detail="Search word cannot be empty.")

    data = await file.read()
    doc = fitz.open(stream=data, filetype="pdf")

    flags = 0 if case_sensitive else fitz.TEXT_PRESERVE_WHITESPACE
    search_flags = fitz.TEXT_DEHYPHENATE
    if not case_sensitive:
        search_flags |= fitz.TEXT_PRESERVE_LIGATURES

    total_found = 0

    for page in doc:
        # quads=True gives precise bounding quads for each hit
        hits = page.search_for(word, quads=True, flags=search_flags if case_sensitive else 0)
        if not hits:
            # fallback: case-insensitive via text extraction
            hits = page.search_for(word, quads=True)

        if not hits:
            continue

        total_found += len(hits)

        if action == "redact":
            for quad in hits:
                # Add a black redaction annotation
                annot = page.add_redact_annot(quad, fill=(0, 0, 0))
            page.apply_redactions()

        elif action == "replace":
            for quad in hits:
                # Redact with white fill, then insert replacement text
                rect = quad.rect
                annot = page.add_redact_annot(
                    quad,
                    text=replacement,
                    fontsize=0,   # auto-fit
                    fill=(1, 1, 1),  # white background
                    text_color=(0, 0, 0),
                )
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        elif action == "highlight":
            for quad in hits:
                page.add_highlight_annot(quad)

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    if total_found == 0:
        raise HTTPException(status_code=404, detail=f'Word "{word}" not found in the PDF.')

    out_buf = io.BytesIO()
    doc.save(out_buf, garbage=4, deflate=True)
    doc.close()
    out_buf.seek(0)

    safe_name = file.filename.replace(" ", "_")
    return Response(
        content=out_buf.read(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="edited_{safe_name}"',
            "X-Words-Found": str(total_found),
        },
    )


@app.post("/count")
async def count_occurrences(
    file: UploadFile = File(...),
    word: str = Form(...),
):
    """Count how many times a word appears without modifying the PDF."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    data = await file.read()
    doc = fitz.open(stream=data, filetype="pdf")

    results = []
    total = 0
    for i, page in enumerate(doc, start=1):
        hits = page.search_for(word, quads=True)
        count = len(hits)
        total += count
        if count:
            results.append({"page": i, "count": count})

    doc.close()
    return {"total": total, "pages": results, "word": word}
