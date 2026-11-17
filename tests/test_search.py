"""Integration tests use a disposable schema, never modify the demo collection."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg.conninfo import make_conninfo

import vector_service as service
from app import SearchRequest


def vector(axis=0):
    values = [0.0] * service.DIMENSIONS
    values[axis] = 1.0
    return values


class PureTests(unittest.TestCase):
    def test_vietnamese_normalization(self):
        self.assertEqual(service.normalize_text('MÈO ĐẤM BỐC'), 'meo dam boc')

    def test_invalid_vectors_and_blank_queries(self):
        for values in ([0] * 768, [1], [float('nan')] * 768):
            with self.assertRaises(service.EmbeddingError):
                service.validate_vector(values)
        with self.assertRaises(ValueError):
            SearchRequest(query='   ')
        with self.assertRaises(ValueError):
            SearchRequest(query='cat', top_k=11)

    def test_actual_visual_is_used(self):
        items = service.get_stickers_metadata()
        self.assertTrue(items[0]['visual_description'])
        self.assertIn(items[0]['visual'], service.document_for(items[0]))

    def test_query_prompt_and_cache(self):
        service.query_embedding.cache_clear()
        with patch.object(service, 'embed', return_value=vector()) as mock:
            a = service.query_embedding('test', 'model-a')
            b = service.query_embedding('test', 'model-a')
            self.assertEqual(a, b)
            mock.assert_called_once_with('task: search result | query: test', model='model-a')
            service.query_embedding('test', 'model-b')
            self.assertEqual(mock.call_count, 2)
        service.query_embedding.cache_clear()

    def test_cache_distinguishes_text_and_image_and_model(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(service, 'CACHE_DIR', Path(directory)), patch.object(service, 'embed', return_value=vector()) as mock:
                service.cached_embedding(b'test', 'text')
                service.cached_embedding(b'test', 'text')
                service.cached_embedding(b'test', 'image')
                with patch.object(service, 'DEFAULT_MODEL', 'another-model'):
                    service.cached_embedding(b'test', 'text')
                self.assertEqual(mock.call_count, 3)
                self.assertEqual(mock.call_args_list[1].args[0].inline_data.data, b'test')


@unittest.skipUnless(os.getenv('RUN_DB_TESTS') == '1', 'set RUN_DB_TESTS=1 for disposable PostgreSQL tests')
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_url = service.DB_URL
        cls.schema = 'test_meme_' + uuid.uuid4().hex
        with psycopg.connect(cls.original_url) as conn:
            conn.execute(f'CREATE SCHEMA {cls.schema}')
        service.DB_URL = make_conninfo(cls.original_url, options=f'-csearch_path={cls.schema},public')
        service.init_db()
        cls.items = [dict(item) for item in service.get_stickers_metadata()[:2]]
        cls.items[0].update(name='Mèo đấm bốc', caption='đấu võ', tags=['đấm'], visual_description='găng tay')
        cls.items[1].update(name='Mèo ngủ', caption='ngủ ngon', tags=['ngủ'], visual_description='nhắm mắt')
        def embedding(payload, kind, api_key=None):
            assert kind == 'image', 'Ingestion must only request image embeddings'
            return vector(1 if payload == (service.BASE_DIR / cls.items[0]['image_path']).read_bytes() else 0)
        with patch.object(service, 'get_stickers_metadata', return_value=cls.items), patch.object(service, 'cached_embedding', side_effect=embedding):
            service.seed_database()

    @classmethod
    def tearDownClass(cls):
        service.DB_URL = cls.original_url
        with psycopg.connect(cls.original_url) as conn:
            conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    def test_two_branches_same_corpus_distinct_rankings(self):
        with patch.object(service, 'query_embedding', return_value=tuple(vector())) as mock:
            mock.cache_info.return_value.hits = 0
            result = service.search_compare('meo dam boc', 2)
        groups = result['methods']
        self.assertEqual(groups['keyword']['results'][0]['id'], self.items[0]['id'])
        self.assertEqual(set(groups), {'keyword', 'image'})
        self.assertEqual(groups['image']['results'][0]['id'], self.items[1]['id'])
        mock.assert_called_once()
        for kind in ('image',):
            self.assertEqual(len(groups[kind]['results']), 2)
            self.assertEqual(groups[kind]['score_type'], 'cosine_similarity')

    def test_no_keyword_match_and_provider_failure(self):
        with patch.object(service, 'query_embedding', side_effect=service.EmbeddingError('quota')):
            result = service.search_compare('xyzunknown')
        self.assertEqual(result['methods']['keyword']['results'], [])
        self.assertEqual(result['methods']['keyword']['status'], 'ok')
        self.assertEqual(result['methods']['image']['status'], 'error')
        self.assertEqual(result['methods']['image']['error'], 'quota')

    def test_failed_rebuild_keeps_old_collection(self):
        old = service.get_stats()['collection_id']
        changed = [dict(self.items[0], caption='new caption'), self.items[1]]
        with patch.object(service, 'get_stickers_metadata', return_value=changed), patch.object(service, 'cached_embedding', side_effect=service.EmbeddingError('quota')):
            with self.assertRaises(service.EmbeddingError):
                service.seed_database()
        self.assertEqual(service.get_stats()['collection_id'], old)
        self.assertEqual(service.get_stats()['sticker_count'], 2)

    def test_identical_seed_skips_provider_and_vector_endpoint(self):
        with patch.object(service, 'get_stickers_metadata', return_value=self.items), patch.object(service, 'cached_embedding') as mock:
            result = service.seed_database()
        self.assertEqual(result['status'], 'unchanged')
        mock.assert_not_called()
        result = service.get_sticker_vector(self.items[0]['id'])
        self.assertEqual(len(result['vector']), 768)
        self.assertIsNone(service.get_sticker_vector('missing'))


if __name__ == '__main__':
    unittest.main()
