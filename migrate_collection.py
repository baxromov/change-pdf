"""
Duplicate hr-assistent → hr-assistant-v2, removing all Ipoteka-Bank / OTP Group
brand references from the page_content payload field.
Original collection is never modified.

Usage:
    cp .env.example .env   # fill in QDRANT_URL and QDRANT_API_KEY
    uv sync
    python migrate_collection.py
"""

import os
import re
import sys

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

load_dotenv()

SOURCE = "hr-assistant"
TARGET = "hr-assistant-v2"
SCROLL_BATCH = 100

# All brand-name patterns to strip from page_content (case-insensitive)
_BRAND_PATTERNS = [
    r'ОАО\s*[«\"]?\s*Ипотека[- ]Банк\s*[»\"]?',  # legal name, Cyrillic
    r'Ипотека[- ]Банк',                             # Cyrillic short form
    r'Ipoteka[- ]Bank',                             # Latin form (both variants)
    r'OTP\s+Group',
]
_BRAND_RE = re.compile(
    '|'.join(_BRAND_PATTERNS),
    flags=re.IGNORECASE,
)


def clean(text: str) -> str:
    cleaned = _BRAND_RE.sub('', text)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)   # collapse extra spaces
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)    # collapse extra newlines
    return cleaned.strip()


def get_client() -> QdrantClient:
    url = os.getenv('QDRANT_URL')
    api_key = os.getenv('QDRANT_API_KEY')
    if not url or not api_key:
        sys.exit('ERROR: QDRANT_URL and QDRANT_API_KEY must be set in .env')
    return QdrantClient(url=url, api_key=api_key)


def main() -> None:
    client = get_client()

    # Verify source exists
    existing = {c.name for c in client.get_collections().collections}
    if SOURCE not in existing:
        sys.exit(f'ERROR: collection "{SOURCE}" not found in Qdrant')

    # If target already exists, skip — no need to re-copy vectors
    if TARGET in existing:
        src_count = client.count(SOURCE).count
        tgt_count = client.count(TARGET).count
        if tgt_count >= src_count:
            sys.exit(
                f'"{TARGET}" already exists with {tgt_count} points '
                f'(source has {src_count}). Nothing to do.'
            )
        print(
            f'"{TARGET}" exists but is incomplete ({tgt_count}/{src_count} points). '
            'Resuming migration…'
        )

    # Read source vector config
    info = client.get_collection(SOURCE)
    vectors_config = info.config.params.vectors

    # Build VectorParams for target (supports both named and unnamed vectors)
    if isinstance(vectors_config, dict):
        target_vectors = {
            name: VectorParams(size=cfg.size, distance=cfg.distance)
            for name, cfg in vectors_config.items()
        }
    else:
        target_vectors = VectorParams(
            size=vectors_config.size,
            distance=vectors_config.distance,
        )

    if TARGET not in existing:
        client.create_collection(TARGET, vectors_config=target_vectors)
        print(f'Created collection "{TARGET}".')

    existing_ids: set = set()
    if TARGET in existing:
        ids_result, _ = client.scroll(
            collection_name=TARGET, limit=10_000, with_vectors=False, with_payload=False
        )
        existing_ids = {pt.id for pt in ids_result}

    # Scroll, clean, upsert
    total = modified = 0
    offset = None

    while True:
        results, offset = client.scroll(
            collection_name=SOURCE,
            limit=SCROLL_BATCH,
            offset=offset,
            with_vectors=True,
            with_payload=True,
        )
        if not results:
            break

        cleaned_points: list[PointStruct] = []
        for pt in results:
            if pt.id in existing_ids:
                total += 1
                continue
            payload = dict(pt.payload or {})
            if 'page_content' in payload:
                original = payload['page_content']
                cleaned_text = clean(original)
                if cleaned_text != original:
                    modified += 1
                payload['page_content'] = cleaned_text
            cleaned_points.append(
                PointStruct(id=pt.id, vector=pt.vector, payload=payload)
            )

        if cleaned_points:
            client.upsert(collection_name=TARGET, points=cleaned_points)
        total += len(cleaned_points)
        print(f'  processed {total} points...', end='\r')

        if offset is None:
            break

    print(f'\nDone. {total} points copied, {modified} had brand text removed.')
    print(f'Source "{SOURCE}" is untouched. New collection: "{TARGET}".')


if __name__ == '__main__':
    main()
