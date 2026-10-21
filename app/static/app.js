(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const roleNames = { ADMIN: 'Quản trị viên', INSTRUCTOR: 'Giảng viên', STUDENT: 'Sinh viên' };
  // Keep bearer tokens in memory only. Reloading ends the browser session.
  let token = null;
  let user = null;
  let expiryTimer;
  const accountPage = location.pathname === '/account';
  $('home-page').hidden = accountPage;
  $('account-page').hidden = !accountPage;
  $('breadcrumb').textContent = accountPage ? 'Tài khoản' : 'Trang chủ';
  document.title = (accountPage ? 'Tài khoản' : 'Trang chủ') + ' · miniLMS';
  document.querySelector(`[data-page="${accountPage ? 'account' : 'home'}"]`).classList.add('active');
  document.querySelector(`[data-page="${accountPage ? 'account' : 'home'}"]`).setAttribute('aria-current', 'page');

  // Navigate between the two views without reloading or persisting the token.
  document.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    const url = new URL(link.href);
    if (url.origin !== location.origin || !['/', '/home', '/account'].includes(url.pathname)) return;
    event.preventDefault();
    history.pushState({}, '', url.pathname + url.hash);
    showPage();
    if (url.hash) document.querySelector(url.hash)?.scrollIntoView();
    else window.scrollTo(0, 0);
  });
  function showPage() {
    const isAccount = location.pathname === '/account';
    $('home-page').hidden = isAccount;
    $('account-page').hidden = !isAccount;
    $('breadcrumb').textContent = isAccount ? 'Tài khoản' : 'Trang chủ';
    document.title = (isAccount ? 'Tài khoản' : 'Trang chủ') + ' · miniLMS';
    document.querySelectorAll('[data-page]').forEach(link => {
      const active = link.dataset.page === (isAccount ? 'account' : 'home');
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }
  window.addEventListener('popstate', showPage);
  function empty(title, description, signIn = false) {
    const box = document.createElement('div');
    box.className = 'empty-state';
    const icon = document.createElement('span');
    icon.textContent = '▤'; icon.setAttribute('aria-hidden', 'true');
    const content = document.createElement('div');
    const heading = document.createElement('h3'); heading.textContent = title;
    const text = document.createElement('p'); text.textContent = description;
    content.append(heading, text);
    if (signIn) {
      const link = document.createElement('a'); link.href = '/account'; link.textContent = 'Đăng nhập để tiếp tục ↗'; content.append(link);
    }
    box.append(icon, content); $('course-grid').replaceChildren(box);
  }
  function reset(message = '') {
    clearTimeout(expiryTimer); token = null; user = null;
    $('login-panel').hidden = false; $('profile-panel').hidden = true;
    $('header-name').textContent = 'Tài khoản của bạn';
    $('header-avatar').textContent = $('profile-avatar').textContent = 'M';
    $('profile-role').textContent = 'Chào mừng bạn';
    $('profile-title').textContent = 'Cùng bắt đầu nhé.';
    $('profile-description').textContent = 'Đăng nhập để mở không gian học tập của riêng bạn.';
    $('role-stat').textContent = 'Khách'; $('course-count').textContent = $('average').textContent = '—';
    $('session-caption').textContent = 'ĐĂNG NHẬP ĐỂ BẮT ĐẦU';
    $('course-pill').textContent = 'Không gian học tập';
    $('profile-email').textContent = $('profile-id').textContent = $('profile-role-detail').textContent = '';
    $('account-message').textContent = message; $('home-message').textContent = '';
    empty('Hành trình của bạn bắt đầu tại đây', 'Đăng nhập để xem khóa học và kết quả học tập của bạn.', true);
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401 && path !== '/auth/login') reset('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.');
      throw new Error(data.error || 'SERVER_ERROR');
    }
    return data;
  }
  async function loadCourses() {
    $('home-message').textContent = 'Đang tải khóa học…';
    try {
      const { courses } = await api('/dashboard');
      $('home-message').textContent = '';
      $('course-count').textContent = courses.length;
      $('course-pill').textContent = `${courses.length} khóa học`;
      const scores = courses.map(c => c.score).filter(s => s !== null);
      $('average').textContent = scores.length ? (scores.reduce((a, b) => a + b, 0) / scores.length).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) : '—';
      if (!courses.length) { empty('Chưa có khóa học', 'Các khóa học được phân công hoặc ghi danh sẽ xuất hiện tại đây.'); return; }
      $('course-grid').replaceChildren();
      courses.forEach((course, index) => {
        const card = document.createElement('article'); card.className = 'course-card';
        const cover = document.createElement('div'); cover.className = 'course-cover' + (index % 2 ? ' database' : '');
        const symbol = document.createElement('b'); symbol.textContent = index % 2 ? '{ db }' : '</>';
        const code = document.createElement('span'); code.textContent = course.id.toUpperCase(); cover.append(symbol, code);
        const body = document.createElement('div'); body.className = 'course-body';
        const title = document.createElement('h3'); title.textContent = course.title;
        const instructor = document.createElement('p'); instructor.textContent = 'Giảng viên · ' + course.instructor;
        const result = document.createElement('div'); result.className = 'course-result';
        const label = document.createElement('span'); label.textContent = 'Điểm học tập';
        const score = document.createElement('strong'); score.textContent = course.score === null ? 'Chưa có điểm cá nhân' : `${course.score.toLocaleString('vi-VN')} / 10`;
        result.append(label, score); body.append(title, instructor, result); card.append(cover, body); $('course-grid').append(card);
      });
    } catch (error) {
      if (user) { $('home-message').textContent = 'Không tải được khóa học. Vui lòng thử lại.'; empty('Kết nối bị gián đoạn', 'Bạn có thể thử tải lại danh sách.'); const retry = document.createElement('button'); retry.className = 'button outline'; retry.textContent = 'Thử lại'; retry.onclick = loadCourses; $('course-grid').append(retry); }
    }
  }
  $('toggle-password').addEventListener('click', () => {
    const show = $('password').type === 'password'; $('password').type = show ? 'text' : 'password';
    $('toggle-password').textContent = show ? 'Ẩn' : 'Hiện'; $('toggle-password').setAttribute('aria-label', show ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
  });
  $('login-form').addEventListener('submit', async event => {
    event.preventDefault(); $('login-button').disabled = true; $('account-message').textContent = 'Đang đăng nhập…';
    try {
      const result = await api('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: $('email').value.trim(), password: $('password').value }) });
      token = result.accessToken;
      user = await api('/me');
      $('password').value = ''; $('password').type = 'password'; $('toggle-password').textContent = 'Hiện'; $('toggle-password').setAttribute('aria-label', 'Hiện mật khẩu');
      $('login-panel').hidden = true; $('profile-panel').hidden = false;
      $('header-name').textContent = user.email;
      $('header-avatar').textContent = $('profile-avatar').textContent = user.email[0].toUpperCase();
      $('profile-title').textContent = user.email.split('@')[0];
      $('profile-description').textContent = 'Không gian học tập của bạn đã sẵn sàng.';
      $('profile-email').textContent = user.email; $('profile-id').textContent = user.id;
      $('profile-role-detail').textContent = $('profile-role').textContent = $('role-stat').textContent = roleNames[user.role] || user.role;
      $('session-caption').textContent = 'ĐÃ KẾT NỐI KHÔNG GIAN HỌC TẬP';
      $('account-message').textContent = '';
      expiryTimer = setTimeout(() => reset('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'), result.expiresIn * 1000);
      await loadCourses();
    } catch (error) {
      reset();
      $('account-message').textContent = ({ INVALID_CREDENTIALS: 'Email hoặc mật khẩu không chính xác.', ACCOUNT_LOCKED: 'Tài khoản tạm khóa. Vui lòng thử lại sau 15 phút.' })[error.message] || 'Không thể đăng nhập. Vui lòng thử lại.';
    } finally { $('login-button').disabled = false; }
  });
  $('logout').addEventListener('click', () => { reset('Bạn đã đăng xuất.'); $('email').value = ''; $('password').value = ''; });
  reset();
})();
