from app.jira_client import JiraClient, field_names


def test_jira_field_names_normalize_strings_and_objects():
    assert field_names(["M&S", {"name": "Signet"}, {"value": "M&S"}]) == ["M&S", "Signet"]


def test_jira_field_names_accept_scalar_values():
    assert field_names({"value": "Sorted Group"}) == ["Sorted Group"]


def test_jql_can_cover_all_projects(monkeypatch):
    client = JiraClient('example.atlassian.net', 'u', 't')
    seen = {}
    def fake_get(path, params):
        seen.update(params)
        return {'issues': []}
    monkeypatch.setattr(client, '_get', fake_get)
    list(client.search_issues(since='2022-01-01', project='', organisation_field='customfield_10002', customer_field='customfield_10070', use_created=True))
    assert seen['jql'].startswith('created >=')


def test_jql_can_limit_to_project(monkeypatch):
    client = JiraClient('example.atlassian.net', 'u', 't')
    seen = {}
    monkeypatch.setattr(client, '_get', lambda path, params: (seen.update(params) or {'issues': []}))
    list(client.search_issues(since='2022-01-01', project='CS', organisation_field='customfield_10002', customer_field='customfield_10070', use_created=True))
    assert seen['jql'].startswith('project = CS AND')
