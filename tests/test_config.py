import pytest
from app.config import Settings


def test_config_requires_token_and_team(monkeypatch):
    monkeypatch.delenv('TEMPO_TOKEN', raising=False); monkeypatch.delenv('TEMPO_TEAM_ID', raising=False)
    with pytest.raises(ValueError): Settings.from_env()


def test_overlap_defaults_to_five_minutes(monkeypatch):
    monkeypatch.setenv('TEMPO_TOKEN', 'tempo')
    monkeypatch.setenv('TEMPO_TEAM_ID', '29')
    monkeypatch.setenv('JIRA_DOMAIN', 'example.atlassian.net')
    monkeypatch.setenv('JIRA_USER_EMAIL', 'user@example.com')
    monkeypatch.setenv('JIRA_API_TOKEN', 'jira')
    assert Settings.from_env().overlap_seconds == 300
