from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import threading
import unicodedata
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
DB_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgrespassword@localhost:5432/sticker_vector_db')
DEFAULT_MODEL = os.getenv('EMBEDDING_MODEL', 'gemini-embedding-2')
DIMENSIONS = 768
PIPELINE_VERSION = 'meme-search-v1'
CACHE_DIR = BASE_DIR / '.cache' / 'embeddings'
_ingest_lock = threading.Lock()
_next_ingest_request = 0.0


class EmbeddingError(RuntimeError):
    pass


def normalize_text(text: str) -> str:
    text = unicodedata.normalize('NFD', text.lower().replace('đ', 'd'))
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn')


def get_connection():
    conn = psycopg.connect(DB_URL, row_factory=dict_row, connect_timeout=5)
    try:
        register_vector(conn)
    except Exception:
        conn.close()
        raise
    return conn


def init_db():
    # Bootstrap the extension BEFORE registering its types on normal connections.
    with psycopg.connect(DB_URL, connect_timeout=5) as conn:
        conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
        conn.execute('''CREATE TABLE IF NOT EXISTS meme_collections (
            id text PRIMARY KEY, model text NOT NULL, dimensions int NOT NULL,
            pipeline_version text NOT NULL, active boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now())''')
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS one_active_meme_collection
            ON meme_collections (active) WHERE active''')
        conn.execute('''CREATE TABLE IF NOT EXISTS meme_items (
            collection_id text REFERENCES meme_collections(id), id text NOT NULL,
            name text NOT NULL, caption text NOT NULL, tags jsonb NOT NULL,
            image_path text NOT NULL, visual_description text NOT NULL,
            document text NOT NULL, search_document tsvector NOT NULL,
            image_embedding vector(768) NOT NULL,
            PRIMARY KEY (collection_id, id))''')
        conn.execute('CREATE INDEX IF NOT EXISTS meme_keywords ON meme_items USING gin(search_document)')
        # Older collections retain their text vectors; new image-only rows leave them empty.
        if conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='meme_items' AND column_name='text_embedding'").fetchone():
            conn.execute('ALTER TABLE meme_items ALTER COLUMN text_embedding DROP NOT NULL')
        for kind in ('image',):
            conn.execute(f'''CREATE INDEX IF NOT EXISTS meme_{kind}_hnsw
                ON meme_items USING hnsw ({kind}_embedding vector_cosine_ops)''')


def get_stickers_metadata() -> list[dict[str, Any]]:
    cache = json.loads((BASE_DIR / 'stickers_cache.json').read_text(encoding='utf-8'))
    items = sorted(cache.values(), key=lambda item: item['id'])
    if not items:
        raise ValueError('The meme collection is empty.')
    for item in items:
        image = (BASE_DIR / item['image_path']).resolve()
        if not image.is_relative_to(BASE_DIR / 'stickers') or not image.is_file():
            raise ValueError(f"Invalid image: {item['id']}")
        item['visual_description'] = item.get('visual', item.get('default_visual', ''))
    return items


def document_for(item: dict) -> str:
    return (f"title: {item['name']} | text: {item['caption']} "
            f"Tags: {', '.join(item.get('tags', []))}. "
            f"Visual description: {item['visual_description']}")


def validate_vector(values) -> list[float]:
    if values is None or len(values) != DIMENSIONS:
        raise EmbeddingError('Gemini returned an embedding with the wrong dimensions.')
    vector = [float(v) for v in values]
    norm = math.sqrt(sum(v * v for v in vector))
    if not math.isfinite(norm) or norm == 0:
        raise EmbeddingError('Gemini returned an invalid embedding.')
    return [v / norm for v in vector]


def embed(contents, api_key: str | None = None, model: str = DEFAULT_MODEL, wait_for_quota=False) -> list[float]:
    global _next_ingest_request
    key = api_key or os.getenv('GEMINI_API_KEY', '').strip()
    if not key:
        raise EmbeddingError('GEMINI_API_KEY is not configured on the server.')
    # Bounded timeout/retries; never leak provider response or credentials to clients.
    attempts = 5 if wait_for_quota else 3
    for attempt in range(attempts):
        if wait_for_quota:
            # 75 requests/minute leaves headroom under the observed free-tier 100 RPM.
            with _ingest_lock:
                now = time.monotonic()
                slot = max(now, _next_ingest_request)
                _next_ingest_request = slot + 0.8
            time.sleep(max(0, slot - now))
        try:
            with genai.Client(api_key=key, http_options=types.HttpOptions(
                timeout=20000, retry_options=types.HttpRetryOptions(attempts=1)
            )) as client:
                response = client.models.embed_content(
                    model=model, contents=contents,
                    config=types.EmbedContentConfig(output_dimensionality=DIMENSIONS),
                )
            return validate_vector(response.embeddings[0].values)
        except EmbeddingError:
            raise
        except Exception as exc:
            code = getattr(exc, 'code', None)
            if code == 429 and wait_for_quota and attempt < attempts - 1:
                retry = re.search(r'retry in ([0-9.]+)s', str(getattr(exc, 'message', '')), re.I)
                delay = min(60, float(retry.group(1)) + 1) if retry else 30
                with _ingest_lock:
                    _next_ingest_request = max(_next_ingest_request, time.monotonic() + delay)
                continue
            if code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            if code == 429:
                raise EmbeddingError('Gemini is rate-limited. Please try again shortly.') from None
            if code in (400, 403, 404):
                raise EmbeddingError('The Gemini key or model does not support this embedding request.') from None
            raise EmbeddingError('Could not connect to Gemini. Please try again.') from None
    raise EmbeddingError('Gemini is unavailable.')


def cached_embedding(payload: bytes, kind: str, api_key=None) -> list[float]:
    digest = hashlib.sha256(DEFAULT_MODEL.encode() + str(DIMENSIONS).encode() +
                            PIPELINE_VERSION.encode() + kind.encode() + payload).hexdigest()
    path = CACHE_DIR / f'{digest}.json'
    if path.exists():
        return validate_vector(json.loads(path.read_text()))
    contents = payload.decode('utf-8') if kind == 'text' else types.Part.from_bytes(data=payload, mime_type='image/png')
    vector = embed(contents, api_key, wait_for_quota=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=CACHE_DIR, suffix='.tmp', delete=False) as handle:
        handle.write(json.dumps(vector))
        temporary = Path(handle.name)
    temporary.replace(path)
    return vector


@lru_cache(maxsize=128)
def query_embedding(query: str, model: str) -> tuple[float, ...]:
    return tuple(embed(f'task: search result | query: {query}', model=model))


def seed_database(api_key=None, use_vision_llm=False, progress=None):
    init_db()
    items = get_stickers_metadata()
    # Hash the exact text and image bytes so unchanged data resumes from the cache.
    digest = hashlib.sha256(f'{DEFAULT_MODEL}:{DIMENSIONS}:{PIPELINE_VERSION}:image-only'.encode())
    prepared = []
    for item in items:
        document = document_for(item)
        image = (BASE_DIR / item['image_path']).read_bytes()
        digest.update(json.dumps(item, sort_keys=True, ensure_ascii=False).encode())
        digest.update(image)
        prepared.append((item, document, image))
    collection_id = digest.hexdigest()
    with get_connection() as conn:
        existing = conn.execute('SELECT id FROM meme_collections WHERE id=%s AND active', (collection_id,)).fetchone()
        if existing:
            return {'status': 'unchanged', 'count': len(items), 'model': DEFAULT_MODEL, 'collection_id': collection_id}
    # Reuse cached image vectors; metadata changes do not require provider calls.
    def prepare_vectors(entry):
        item, document, image = entry
        image_vector = cached_embedding(image, 'image', api_key)
        return item, document, image_vector
    vectors = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        for i, entry in enumerate(executor.map(prepare_vectors, prepared), 1):
            vectors.append(entry)
            if progress:
                progress(i, len(items), entry[0]['name'])
    # No provider calls inside the transaction. Publish only a complete collection.
    with get_connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('meme-collection-publish'))")
        conn.execute('''INSERT INTO meme_collections (id,model,dimensions,pipeline_version)
            VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING''',
            (collection_id, DEFAULT_MODEL, DIMENSIONS, PIPELINE_VERSION))
        for item, document, iv in vectors:
            conn.execute('''INSERT INTO meme_items (collection_id,id,name,caption,tags,image_path,
                visual_description,document,search_document,image_embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,to_tsvector('simple',%s),%s)
                ON CONFLICT (collection_id,id) DO NOTHING''', (
                collection_id, item['id'], item['name'], item['caption'],
                json.dumps(item.get('tags', []), ensure_ascii=False), item['image_path'],
                item['visual_description'], document, normalize_text(document), Vector(iv)))
        conn.execute('UPDATE meme_collections SET active=false WHERE active')
        conn.execute('UPDATE meme_collections SET active=true WHERE id=%s', (collection_id,))
    query_embedding.cache_clear()
    return {'status': 'success', 'count': len(items), 'model': DEFAULT_MODEL, 'collection_id': collection_id}


def active_collection(conn):
    return conn.execute('SELECT * FROM meme_collections WHERE active').fetchone()


def public_item(row):
    return {key: row[key] for key in ('id', 'name', 'caption', 'tags', 'visual_description')} | {'image': '/' + row['image_path']}


def get_all_stickers():
    with get_connection() as conn:
        rows = conn.execute('''SELECT i.* FROM meme_items i JOIN meme_collections c
            ON c.id=i.collection_id WHERE c.active ORDER BY i.id''').fetchall()
    return [public_item(row) for row in rows]


def get_stats():
    with get_connection() as conn:
        collection = active_collection(conn)
        count = conn.execute('''SELECT count(*) AS n FROM meme_items WHERE collection_id=%s''',
                             (collection['id'] if collection else '',)).fetchone()['n']
        version = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()['extversion']
    return {'database': 'PostgreSQL + pgvector', 'dimensions': DIMENSIONS, 'total_vectors': count,
            'sticker_count': count, 'model': collection['model'] if collection else DEFAULT_MODEL,
            'models': [collection['model']] if collection else [], 'ready': bool(collection),
            'pgvector_version': version, 'index_type': 'HNSW cosine',
            'collection_id': collection['id'] if collection else None}


def result_group(kind):
    return {'status': 'ok', 'score_type': 'full_text_rank' if kind == 'keyword' else 'cosine_similarity',
            'retrieval_ms': 0, 'results': [], 'error': None}


def search_compare(query: str, top_k: int = 5):
    query = query.strip()
    if not query:
        raise ValueError('Enter a meme search query.')
    groups = {kind: result_group(kind) for kind in ('keyword', 'image')}
    with get_connection() as conn:
        collection = active_collection(conn)
    response = {'query': query, 'top_k': top_k, 'model': collection['model'] if collection else DEFAULT_MODEL,
                'dimensions': DIMENSIONS, 'collection_id': collection['id'] if collection else None,
                'embedding_ms': 0, 'query_cache_hit': False, 'methods': groups}
    if not collection:
        for group in groups.values():
            group.update(status='unavailable', error='The meme collection is not ready yet. Please try again shortly.')
        return response
    tokens = re.findall(r'[a-z0-9]+', normalize_text(query))
    started = time.perf_counter()
    if tokens:
        with get_connection() as conn:
            rows = conn.execute('''SELECT i.*, ts_rank_cd(search_document,q) AS score
                FROM meme_items i, websearch_to_tsquery('simple',%s) q
                WHERE collection_id=%s AND search_document @@ q
                ORDER BY score DESC, i.id LIMIT %s''',
                (' OR '.join(dict.fromkeys(tokens)), collection['id'], top_k)).fetchall()
        groups['keyword']['results'] = [public_item(r) | {'score': float(r['score'])} for r in rows]
    groups['keyword']['retrieval_ms'] = round((time.perf_counter() - started) * 1000, 2)
    started = time.perf_counter()
    try:
        before = query_embedding.cache_info().hits
        vector = Vector(list(query_embedding(query, collection['model'])))
        response['query_cache_hit'] = query_embedding.cache_info().hits > before
    except EmbeddingError as exc:
        for kind in ('image',):
            groups[kind].update(status='error', error=str(exc))
        response['embedding_ms'] = round((time.perf_counter() - started) * 1000, 2)
        return response
    response['embedding_ms'] = round((time.perf_counter() - started) * 1000, 2)
    for kind in ('image',):
        started = time.perf_counter()
        try:
            with get_connection() as conn:
                # Exact search over this small corpus ensures both methods see the same set.
                # HNSW indexes are available for larger collections; filters can reduce ANN recall.
                conn.execute('SET LOCAL enable_indexscan = off')
                rows = conn.execute(f'''SELECT *, 1 - ({kind}_embedding <=> %s) AS score
                    FROM meme_items WHERE collection_id=%s
                    ORDER BY {kind}_embedding <=> %s, id LIMIT %s''',
                    (vector, collection['id'], vector, top_k)).fetchall()
            groups[kind]['results'] = [public_item(r) | {'score': round(float(r['score']), 6)} for r in rows]
        except psycopg.Error:
            groups[kind].update(status='error', error='Could not retrieve results. Please try again.')
        groups[kind]['retrieval_ms'] = round((time.perf_counter() - started) * 1000, 2)
    return response


def search_stickers(query, top_k=5, api_key=None):
    result = search_compare(query, top_k)
    group = result['methods']['image']
    return {'query': query, 'dimensions': DIMENSIONS, 'model': result['model'],
            'top_k': top_k, 'results': group['results'], 'status': group['status'], 'error': group['error']}


def get_sticker_vector(sticker_id):
    with get_connection() as conn:
        row = conn.execute('''SELECT i.*, c.model FROM meme_items i JOIN meme_collections c
            ON c.id=i.collection_id WHERE c.active AND i.id=%s''', (sticker_id,)).fetchone()
    if not row:
        return None
    return {'id': row['id'], 'model': row['model'], 'dimensions': DIMENSIONS,
            'vector': row['image_embedding'].to_list()}
