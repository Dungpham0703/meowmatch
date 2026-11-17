from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import vector_service

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    vector_service.init_db()
    yield


app = FastAPI(title='MeowMatch', version='4.0.0', lifespan=lifespan)
app.mount('/stickers', StaticFiles(directory=BASE_DIR / 'stickers'), name='stickers')
app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator('query')
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Enter a meme search query.')
        return value


@app.exception_handler(psycopg.Error)
async def database_error(request, exc):
    logger.error('Database operation failed: %s', type(exc).__name__)
    return JSONResponse(status_code=503, content={'detail': 'The database is unavailable. Please try again.'})


@app.get('/')
def home():
    return FileResponse(BASE_DIR / 'index.html')


@app.get('/api/health')
def health():
    stats = vector_service.get_stats()
    return stats | {'status': 'ok' if stats['ready'] else 'needs_seed',
                    'has_gemini_api_key': bool(os.getenv('GEMINI_API_KEY', '').strip())}


@app.get('/api/stickers')
def list_stickers():
    return vector_service.get_all_stickers()


@app.get('/api/stats')
def stats():
    return vector_service.get_stats()


@app.post('/api/search/compare')
def compare(req: SearchRequest):
    return vector_service.search_compare(req.query, req.top_k)


@app.post('/api/search')
def search(req: SearchRequest):
    return vector_service.search_stickers(req.query, req.top_k)


@app.get('/api/vectors/{sticker_id}')
def vector(sticker_id: str):
    result = vector_service.get_sticker_vector(sticker_id)
    if result is None:
        raise HTTPException(404, 'Meme not found.')
    return result
