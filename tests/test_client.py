import json
from urllib.error import HTTPError
from app.tempo_client import TempoClient


def test_pages_offset(monkeypatch):
    calls = []
    payloads = [
        {"results": [{"id": 1}], "metadata": {"count": 1, "limit": 1}},
        {"results": [], "metadata": {"count": 0, "limit": 1}},
    ]
    def request(path, params):
        calls.append(params); return payloads.pop(0)
    c = TempoClient('https://example', 'x'); monkeypatch.setattr(c, 'request', request)
    assert list(c.pages('/x', {'limit': 1})) == [{'id': 1}]
    assert calls[0]['offset'] == 0


def test_pages_token(monkeypatch):
    payloads = [{"results": [{"id": 1}], "metadata": {"nextPageToken": "next", "limit": 50}}, {"results": [], "metadata": {}}]
    calls = []
    c = TempoClient('https://example', 'x'); monkeypatch.setattr(c, 'request', lambda p, q: (calls.append(q) or payloads.pop(0)))
    assert list(c.pages('/x')) == [{'id': 1}]
    assert calls[1]['nextPageToken'] == 'next'
