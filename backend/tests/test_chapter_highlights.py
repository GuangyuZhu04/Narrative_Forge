"""Run with unittest; uses only an isolated in-memory SQLite database."""
import unittest

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.main import app, ensure_runtime_schema
from app.models.base import Base


class ChapterHighlightTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async def session():
            async with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = session
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url='http://test')
        project = await self.client.post('/api/v1/projects', json={'name': '阅读回归'})
        self.project_id = project.json()['id']
        self.base = f'/api/v1/projects/{self.project_id}/chapters'
        response = await self.client.post(self.base, json={'title': '第一章', 'content': '雨落城门。她推开门。'})
        self.chapter_id = response.json()['id']
        self.route = f'{self.base}/{self.chapter_id}'
        self.mark = {'id': 'test-highlight', 'start': 0, 'end': 4, 'text': '雨落城门', 'prefix': '', 'suffix': '。她推开门。', 'color': 'yellow'}

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()

    async def test_round_trip_and_independent_content_saves(self):
        saved = await self.client.put(self.route, json={'highlights': [self.mark]})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['content'], '雨落城门。她推开门。')
        await self.client.put(self.route, json={'content': '雨落城门。她推开木门。', 'word_count': 12})
        loaded = (await self.client.get(self.route)).json()
        self.assertEqual(loaded['highlights'], [self.mark])
        self.assertEqual(loaded['word_count'], 12)
        listed = (await self.client.get(self.base)).json()['data'][0]
        self.assertEqual(listed['highlights'], [self.mark])
        await self.client.put(self.route, json={'highlights': []})
        self.assertEqual((await self.client.get(self.route)).json()['highlights'], [])

    async def test_invalid_marks_are_rejected_without_mutating_content(self):
        for patch in [{'color': 'url(javascript:alert(1))'}, {'start': -1}, {'end': 0}, {'start': 8, 'end': 4}, {'text': ''}]:
            response = await self.client.put(self.route, json={'highlights': [{**self.mark, **patch}]})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual((await self.client.get(self.route)).json()['highlights'], [])

    async def test_project_scope_applies_to_highlight_reads_and_writes(self):
        other = (await self.client.post('/api/v1/projects', json={'name': '另一作品'})).json()['id']
        route = f'/api/v1/projects/{other}/chapters/{self.chapter_id}'
        self.assertEqual((await self.client.get(route)).status_code, 404)
        self.assertEqual((await self.client.put(route, json={'highlights': [self.mark]})).status_code, 404)
        self.assertEqual((await self.client.get(self.route)).json()['highlights'], [])

    async def test_legacy_database_upgrade_is_idempotent_and_preserves_manuscript(self):
        async with self.engine.begin() as connection:
            await connection.execute(text('ALTER TABLE chapters DROP COLUMN highlights'))
            await ensure_runtime_schema(connection)
            await ensure_runtime_schema(connection)
        loaded = (await self.client.get(self.route)).json()
        self.assertEqual(loaded['content'], '雨落城门。她推开门。')
        self.assertEqual(loaded['highlights'], [])


if __name__ == '__main__':
    unittest.main()
