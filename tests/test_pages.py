import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    return create_app({
        'JWT_SECRET': 'test-pages-secret-of-at-least-32-characters',
        'AUDIT_LOG_PATH': str(tmp_path / 'audit.log'),
    }).test_client()


@pytest.mark.parametrize('path', ['/', '/home', '/account', '/static/app.css', '/static/app.js'])
def test_browser_shell_and_assets_are_public(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert b'password_hash' not in response.data
    if path in ['/', '/home', '/account']:
        assert 'visibility:hidden' in response.text
        assert 'chi.sv@lms.test' not in response.text


@pytest.mark.parametrize(('path', 'endpoint', 'heading', 'other_path'), [
    ('/login', 'pages.login_page', 'Đăng nhập tài khoản', '/register'),
    ('/register', 'pages.register_page', 'Tạo tài khoản mới', '/login'),
])
def test_auth_pages_belong_to_pages_blueprint(client, path, endpoint, heading, other_path):
    rules = [rule for rule in client.application.url_map.iter_rules() if rule.rule == path]
    assert len(rules) == 1
    assert rules[0].endpoint == endpoint
    response = client.get(path)
    assert response.status_code == 200
    assert response.mimetype == 'text/html'
    assert heading in response.text
    assert f'href="{other_path}"' in response.text


def test_report_workspace_has_preview_and_download_controls(client):
    response = client.get('/reports')
    assert response.status_code == 200
    assert 'Báo cáo điểm' in response.text
    assert 'id="report-course"' in response.text
    assert 'id="report-preview"' in response.text
    assert 'id="report-download"' in response.text
    assert 'href="/reports"' in response.text
    assert '<a href="/reports" data-page="reports">' in response.text
    assert 'sidebar-note' not in response.text
    assert 'sidebar-bottom' not in response.text
    assert client.get('/static/app.js').status_code == 200


def test_browser_requires_login_before_showing_workspace(client):
    for path in ('/', '/home', '/account', '/reports'):
        response = client.get(path)
        assert response.status_code == 200
        assert 'visibility:hidden' in response.text
        assert "location.replace('/login')" in response.text
        assert 'id="login-form"' not in response.text
    auth_script = client.get('/static/js/auth.js').text
    assert "window.location.assign('/home')" in auth_script


@pytest.mark.parametrize('path', ['/dashboard', '/me', '/courses/c1/grades', '/static/unknown.js'])
def test_data_and_unknown_assets_remain_protected(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(('email', 'ids', 'scores'), [
    ('chi.sv@lms.test', ['c1'], [7.5]),
    ('dung.sv@lms.test', ['c1', 'c2'], [8.0, 6.0]),
    ('an.gv@lms.test', ['c1'], [None]),
    ('admin@lms.test', ['c1', 'c2'], [None, None]),
])
def test_dashboard_respects_membership_and_role(client, email, ids, scores):
    login = client.post('/auth/login', json={'email': email, 'password': 'Lms@2026'})
    token = login.json['accessToken']
    headers = {'Authorization': f'Bearer {token}'}
    assert client.get('/me', headers=headers).json['email'] == email
    response = client.get('/dashboard', headers=headers)
    assert response.status_code == 200
    assert [c['id'] for c in response.json['courses']] == ids
    assert [c['score'] for c in response.json['courses']] == scores
    assert 'password' not in response.text
    assert 'studentId' not in response.text
