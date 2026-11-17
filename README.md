# MeowMatch

**Find your kind of cat.** One query, two ways to search a collection of **400 cat memes**. The interface, meme names, captions, tags, and visual descriptions are in English.

**Live demo:** [http://3.104.167.1](http://3.104.167.1) · [Deployment details](deploy/DEPLOYMENT.md)

| Method | Searches | Ranking |
| --- | --- | --- |
| Keyword Search | Words in meme names, captions, tags, and visual descriptions | PostgreSQL full-text rank |
| Image Semantic Search | Embeddings created directly from image files | Cosine similarity |

Image semantic search uses **Gemini Embedding 2 (`gemini-embedding-2`), 768 dimensions**, for both queries and images. Captions are not included in image embeddings. There is no text semantic search branch, automatic model switching, or simulated embedding fallback.

## Run locally

Requires Python 3.12+, Docker Compose, and a Gemini API key with access to `gemini-embedding-2`.

Image files are excluded from Git by the repository settings. Copy the existing `stickers/` assets from the original machine into a fresh clone before seeding; the metadata alone does not contain the images.

1. Copy `.env.example` to `.env` and set `GEMINI_API_KEY`.
2. Run `./start_mac_linux.sh` (Windows: `start_windows.bat`).
3. Open **http://localhost:8000**.

The script installs dependencies, waits for PostgreSQL, seeds the collection, and starts the server. The key stays on the server. Unchanged images reuse cached embeddings; metadata updates do not regenerate image vectors. Ingestion allows 75 requests/minute to leave headroom under the 100 RPM free-tier limit observed with the current key. Rate-limit responses trigger bounded waits before retrying.

To run the steps separately:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python seed_pgvector.py
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
```

The web server binds to `0.0.0.0` for port forwarding; PostgreSQL binds to localhost. This is a local demo.

## Collection

The selected collection contains 50 original images and 350 additional memes, with **400 active image vectors**. Extra downloads remain in the ignored `.cache/` directory. Images may contain original text; the website's metadata is English.

To add a meme, place its PNG in `stickers/` and add an entry to `stickers_cache.json`:

```json
{
  "my_cat": {
    "id": "my_cat",
    "name": "Exhausted Cat",
    "caption": "When the workday has barely started and you already need a nap.",
    "tags": ["tired", "work", "sleepy"],
    "visual": "A cat lies flat with half-closed eyes and its head resting on a desk.",
    "image_path": "stickers/my_cat.png",
    "language": "en"
  }
}
```

Run `seed_pgvector.py` to publish changes. Removing an entry and seeding excludes it from the new collection. A collection is activated only after all required image vectors are ready; failed ingestion leaves the previous collection active.

The optional downloader imports public cat meme templates:

```sh
.venv/bin/python scripts/expand_memes.py --target 400 --pages 25
.venv/bin/python seed_pgvector.py
```

The default target is 400, so it does nothing when the selected catalog already contains 400 memes. It deduplicates using perceptual hashes and uses `gemini-3.1-flash-lite` to classify and describe candidates in English. This caption model is separate from the embedding model used for search. Animated templates use a static frame. Downloads and captions are cached for resuming interrupted work.

Source URLs, original source titles, and caption model names are retained in the catalog. Additional images come from [Imgflip cat meme templates](https://imgflip.com/memesearch?q=cat). Images remain the property of their respective owners; public availability does not transfer ownership. The original 50 images were supplied with the repository without source records.

`scripts/translate_catalog.py` translates an existing non-English catalog, caching batches and updating metadata atomically. The included catalog is already translated, so rerunning it makes no translation requests.

## API

`POST /api/search/compare`:

```json
{"query": "judgmental cat", "top_k": 5}
```

The response contains `query`, `model`, `collection_id`, `embedding_ms`, `query_cache_hit`, and exactly two groups: `methods.keyword` and `methods.image`. Each group includes `status`, `results`, `score_type`, `retrieval_ms`, and `error`. Gemini failures leave keyword search usable. Queries must contain 1–500 characters after trimming; `top_k` is 1–10.

- `GET /api/health`: collection readiness, meme/vector counts, embedding model, and extension version. Never returns the key.
- `GET /api/stickers`: active collection metadata.
- `GET /api/stats`: collection statistics.
- `POST /api/search`: image semantic search results using the same request shape.
- `GET /api/vectors/{id}`: the meme's image embedding.
- `/docs`: interactive OpenAPI documentation.

API version 4 removes the former text semantic result group. Historical collections and their text vectors are retained in the database; newly published collections require only image vectors. New installations do not create a text vector column. Browser endpoints for editing API keys and reindexing have been removed; configure `.env` and use the CLI.

## Comparing results

Try “cat wearing sunglasses”, “I do not want to go to work”, and “pretending to be fine”. Keyword search lowercases text, removes accents, and matches any query word. Image semantic search can recognize visual content and mood, but may miss cultural references or slang. Cosine scores are not relevance probabilities and cannot be compared numerically with full-text rank.

This small collection uses exact retrieval in pgvector. An image HNSW index is available for larger collections, but this demo does not claim an index speedup without measurement. Retrieval timings include database connection time and exclude query embedding time. Up to 128 query embeddings are cached per server process and cleared on restart. A cached query avoids a new Gemini request; the image vectors are created during ingestion, never per search.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -v
RUN_DB_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
```

Database tests use a disposable schema and mocked Gemini responses. They cover the two search methods, image-only ingestion, provider failure, no keyword matches, atomic collection replacement, repeated seeding, and vector lookup.

Browser tests require Node.js, Playwright, and a running server:

```sh
npm install --no-save @playwright/test
npx playwright install chromium
node tests/browser.cjs
```

The browser test verifies English UI/content, exactly two search methods, live retrieval, desktop/mobile/tablet layouts, keyboard tabs, dialogs, stale-response handling, and failure states. It calls Gemini for uncached test queries. Screenshots and API snapshots are written to the ignored `artifacts/` directory.

## EC2 deployment

See [the standalone EC2 deployment guide](deploy/README.md) for the app + pgvector + Nginx Docker stack. It supports direct HTTP access by IP and keeps the database/API ports private. No AWS resources are created by these files.
