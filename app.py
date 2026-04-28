import base64
import os

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except Exception:
    FITZ_AVAILABLE = False

import streamlit as st
from dotenv import load_dotenv
from minio import Minio
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "hr-assistant")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "documents")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"


# ── Clients ───────────────────────────────────────────────────────────────────
@st.cache_resource
def get_qdrant():
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)


@st.cache_resource
def get_minio():
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


# ── Data helpers ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def list_minio_files():
    client = get_minio()
    try:
        objects = client.list_objects(MINIO_BUCKET, recursive=True)
        return sorted(obj.object_name for obj in objects)
    except Exception as e:
        st.error(f"MinIO error: {e}")
        return []


@st.cache_data(ttl=60)
def get_chunks_for_file(minio_object: str):
    """Filter by metadata.minio_object which stores the full MinIO path."""
    client = get_qdrant()
    results, _ = client.scroll(
        collection_name=QDRANT_COLLECTION,
        scroll_filter=Filter(
            must=[
                FieldCondition(
                    key="metadata.minio_object",
                    match=MatchValue(value=minio_object),
                )
            ]
        ),
        limit=10000,
        with_payload=True,
        with_vectors=False,
    )
    chunks = []
    for pt in results:
        p = pt.payload or {}
        meta = p.get("metadata", {})
        chunks.append(
            {
                "id": pt.id,
                "page_number": meta.get("page_number", 0),
                "doc_id": meta.get("doc_id", ""),
                "source_file": meta.get("source_file", minio_object),
                "minio_object": meta.get("minio_object", minio_object),
                "page_content": p.get("page_content", ""),
            }
        )
    chunks.sort(key=lambda c: c["page_number"])
    return chunks


@st.cache_data(ttl=300)
def get_pdf_bytes(minio_object: str) -> bytes | None:
    client = get_minio()
    try:
        response = client.get_object(MINIO_BUCKET, minio_object)
        data = response.read()
        response.close()
        return data
    except Exception as e:
        st.error(f"MinIO PDF error: {e}")
        return None


def render_pdf_page(pdf_bytes: bytes, page_number: int, dpi: int = 150) -> bytes:
    """Render a PDF page (0-indexed internally, 1-indexed page_number) as PNG bytes."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_idx = max(0, page_number - 1)
    page_idx = min(page_idx, len(doc) - 1)
    page = doc[page_idx]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


@st.cache_data(ttl=60)
def debug_sample(source_file: str):
    """Return first 3 raw payloads without any filter for debugging."""
    client = get_qdrant()
    results, _ = client.scroll(
        collection_name=QDRANT_COLLECTION,
        limit=3,
        with_payload=True,
        with_vectors=False,
    )
    return [pt.payload for pt in results]


# ── UI ────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="PDF Chunk Explorer", layout="wide")
st.title("PDF Chunk Explorer")
st.caption(f"MinIO bucket: `{MINIO_BUCKET}` · Qdrant collection: `{QDRANT_COLLECTION}`")

# Sidebar: file list
with st.sidebar:
    st.header("Files")
    if st.button("Refresh", use_container_width=True):
        list_minio_files.clear()
        get_chunks_for_file.clear()
        debug_sample.clear()

    files = list_minio_files()
    if not files:
        st.info("No files found in MinIO bucket.")
        st.stop()

    selected_file = st.radio("Select a file", files, label_visibility="collapsed")

# Main: pages for the selected file
st.subheader(f"`{selected_file}`")

chunks = get_chunks_for_file(selected_file)
if not chunks:
    st.warning("No chunks found in Qdrant for this file.")
    with st.expander("Debug — raw sample payloads from collection"):
        samples = debug_sample(selected_file)
        if samples:
            st.json(samples)
            st.info(
                "Check that `metadata.minio_object` in the payload matches "
                f"the MinIO object name `{selected_file}` exactly."
            )
        else:
            st.error(f"Collection `{QDRANT_COLLECTION}` is empty or unreachable.")
    st.stop()

pages = sorted({c["page_number"] for c in chunks})
st.write(f"**{len(chunks)} chunks** across **{len(pages)} pages**")

# Page navigator
col_prev, col_picker, col_next = st.columns([1, 3, 1])
if "page_idx" not in st.session_state:
    st.session_state.page_idx = 0

with col_prev:
    if st.button("← Prev", use_container_width=True, disabled=st.session_state.page_idx == 0):
        st.session_state.page_idx -= 1

with col_next:
    if st.button("Next →", use_container_width=True, disabled=st.session_state.page_idx >= len(pages) - 1):
        st.session_state.page_idx += 1

with col_picker:
    chosen_page = st.selectbox(
        "Jump to page",
        pages,
        index=st.session_state.page_idx,
        label_visibility="collapsed",
    )
    st.session_state.page_idx = pages.index(chosen_page)

current_page = pages[st.session_state.page_idx]
st.markdown(f"### Page {current_page}  <sub>({st.session_state.page_idx + 1} / {len(pages)})</sub>", unsafe_allow_html=True)

page_chunks = [c for c in chunks if c["page_number"] == current_page]

col_pdf, col_chunks = st.columns([1, 1])

with col_pdf:
    st.markdown("**PDF sahifasi**")
    pdf_bytes = get_pdf_bytes(selected_file)
    if pdf_bytes:
        if FITZ_AVAILABLE:
            img = render_pdf_page(pdf_bytes, current_page)
            st.image(img, use_container_width=True)
        else:
            b64 = base64.b64encode(pdf_bytes).decode()
            iframe_html = (
                f'<iframe src="data:application/pdf;base64,{b64}#page={current_page}" '
                f'width="100%" height="800px" style="border:none;"></iframe>'
            )
            st.components.v1.html(iframe_html, height=820, scrolling=False)
    else:
        st.warning("PDF yuklab bo'lmadi.")

with col_chunks:
    st.markdown(f"**Chunks ({len(page_chunks)} ta)**")
    for i, chunk in enumerate(page_chunks, 1):
        with st.expander(f"Chunk {i} — doc_id: `{chunk['doc_id']}`", expanded=True):
            st.text_area(
                "page_content",
                value=chunk["page_content"],
                height=200,
                key=f"chunk_{chunk['id']}",
                label_visibility="collapsed",
            )
            st.caption(
                f"page_number: **{chunk['page_number']}** · "
                f"doc_id: `{chunk['doc_id']}` · "
                f"source_file: `{chunk['source_file']}` · "
                f"point_id: `{chunk['id']}`"
            )
