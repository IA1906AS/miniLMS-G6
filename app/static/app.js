(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const roleNames = { ADMIN: 'Quản trị viên', INSTRUCTOR: 'Giảng viên', STUDENT: 'Sinh viên' };
  // Reuse the token from the dedicated login page for this browser tab only.
  let token = sessionStorage.getItem('accessToken');
  let user = null;
  let expiryTimer;
  let reportVersion = 0;
  showPage();

  // Navigate between views without reloading or persisting the token.
  document.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    const url = new URL(link.href);
    if (url.origin !== location.origin || !['/', '/home', '/account', '/reports'].includes(url.pathname)) return;
    event.preventDefault();
    history.pushState({}, '', url.pathname + url.hash);
    showPage();
    if (url.hash) document.querySelector(url.hash)?.scrollIntoView();
    else window.scrollTo(0, 0);
  });
  function showPage() {
    const page = location.pathname === '/account' ? 'account' : location.pathname === '/reports' ? 'reports' : 'home';
    const names = { home: 'Trang chủ', account: 'Tài khoản', reports: 'Báo cáo điểm' };
    $('home-page').hidden = page !== 'home';
    $('account-page').hidden = page !== 'account';
    $('reports-page').hidden = page !== 'reports';
    $('breadcrumb').textContent = names[page];
    document.title = names[page] + ' · miniLMS';
    document.querySelectorAll('[data-page]').forEach(link => {
      const active = link.dataset.page === page;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }
  window.addEventListener('popstate', showPage);
  function reportPlaceholder(message) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 2; cell.className = 'report-empty'; cell.textContent = message;
    row.append(cell); $('report-preview').tBodies[0].replaceChildren(row);
    $('report-count').textContent = '—';
  }
  async function loadReport() {
    const courseId = $('report-course').value;
    const version = ++reportVersion;
    $('report-download').disabled = true;
    if (!courseId || !token) {
      reportPlaceholder('Chọn một khóa học để xem dữ liệu.');
      $('report-message').textContent = '';
      return;
    }
    $('report-scope').textContent = $('report-course').selectedOptions[0].textContent;
    $('report-message').textContent = 'Đang tải bảng điểm…';
    reportPlaceholder('Đang tải dữ liệu…');
    try {
      const rows = await api(`/courses/${encodeURIComponent(courseId)}/grades`);
      if (version !== reportVersion) return;
      const body = $('report-preview').tBodies[0];
      body.replaceChildren();
      rows.forEach(row => {
        const tr = document.createElement('tr');
        const student = document.createElement('td'); student.textContent = row.studentId;
        const score = document.createElement('td'); score.textContent = row.score === null ? 'Chưa có điểm' : `${row.score.toLocaleString('vi-VN')} / 10`;
        tr.append(student, score); body.append(tr);
      });
      if (!rows.length) reportPlaceholder('Khóa học này chưa có điểm.');
      $('report-count').textContent = `${rows.length} bản ghi`;
      $('report-message').textContent = '';
      $('report-download').disabled = false;
    } catch (error) {
      if (version !== reportVersion) return;
      reportPlaceholder('Không tải được điểm. Hãy chọn lại khóa học để thử lại.');
      $('report-message').textContent = user ? 'Không tải được bảng điểm. Vui lòng thử lại.' : 'Phiên đăng nhập đã hết hạn.';
    }
  }
  $('report-course').addEventListener('change', loadReport);
  $('report-download').addEventListener('click', async () => {
    const courseId = $('report-course').value;
    if (!token || !courseId) return;
    const activeToken = token;
    $('report-download').disabled = true;
    $('report-course').disabled = true;
    $('report-message').textContent = 'Đang tạo tệp CSV…';
    try {
      const response = await fetch(`/courses/${encodeURIComponent(courseId)}/grades/export`, {
        headers: { Authorization: `Bearer ${activeToken}` }
      });
      if (!response.ok) {
        const error = await response.json();
        if (response.status === 401) reset();
        throw new Error(error.error || 'SERVER_ERROR');
      }
      const blob = await response.blob();
      if (token !== activeToken) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `grades-${courseId}.csv`;
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      $('report-message').textContent = 'Đã tạo tệp CSV. Trình duyệt sẽ lưu tệp về máy.';
    } catch (error) {
      if (!token) return;
      $('report-message').textContent = error.message === 'EXPORT_BUSY'
        ? 'Hệ thống đang xuất tối đa 2 báo cáo. Vui lòng thử lại sau.'
        : 'Không thể xuất báo cáo. Vui lòng thử lại.';
    } finally {
      $('report-course').disabled = !token;
      $('report-download').disabled = !token || !courseId;
    }
  });
  function empty(title, description) {
    const box = document.createElement('div');
    box.className = 'empty-state';
    const icon = document.createElement('span');
    icon.textContent = '▤'; icon.setAttribute('aria-hidden', 'true');
    const content = document.createElement('div');
    const heading = document.createElement('h3'); heading.textContent = title;
    const text = document.createElement('p'); text.textContent = description;
    content.append(heading, text);
    box.append(icon, content); $('course-grid').replaceChildren(box);
  }
  function reset() {
    clearTimeout(expiryTimer); token = null; user = null; ++reportVersion;
    sessionStorage.removeItem('accessToken');
    sessionStorage.removeItem('accessTokenExpiresAt');
    location.replace('/login');
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401) reset();
      throw new Error(data.error || 'SERVER_ERROR');
    }
    return data;
  }
  async function loadCourses() {
    $('home-message').textContent = 'Đang tải khóa học…';
    const activeToken = token;
    try {
      const { courses } = await api('/dashboard');
      if (!activeToken || token !== activeToken) return;
      $('report-course').replaceChildren(new Option(courses.length ? 'Chọn khóa học' : 'Chưa có khóa học', ''));
      courses.forEach(course => $('report-course').add(new Option(course.title, course.id)));
      $('report-course').disabled = !courses.length;

      $('report-scope').textContent = courses.length ? 'Chọn khóa học để xem trước bảng điểm.' : 'Chưa có khóa học để xuất.';
      $('report-message').textContent = courses.length ? '' : 'Chưa có khóa học để xuất báo cáo.';
      $('home-message').textContent = '';
      $('course-count').textContent = courses.length;
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
      if (user) { $('home-message').textContent = 'Không tải được khóa học. Vui lòng thử lại.'; $('report-message').textContent = 'Không tải được danh sách khóa học. Vui lòng thử lại ở trang chủ.'; empty('Kết nối bị gián đoạn', 'Bạn có thể thử tải lại danh sách.'); const retry = document.createElement('button'); retry.className = 'button outline'; retry.textContent = 'Thử lại'; retry.onclick = loadCourses; $('course-grid').append(retry); }
    }
  }
  $('logout').addEventListener('click', reset);
  async function restoreSession() {
    const expiresAt = Number(sessionStorage.getItem('accessTokenExpiresAt'));
    if (!token || !Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      reset();
      return;
    }
    try {
      user = await api('/me');
      $('header-name').textContent = user.email;
      $('header-avatar').textContent = $('profile-avatar').textContent = user.email[0].toUpperCase();
      $('profile-title').textContent = user.email.split('@')[0];
      $('profile-email').textContent = user.email;
      $('profile-id').textContent = user.id;
      $('profile-role-detail').textContent = $('profile-role').textContent = $('role-stat').textContent = roleNames[user.role] || user.role;

      expiryTimer = setTimeout(reset, Math.min(expiresAt - Date.now(), 2147483647));
      document.documentElement.style.visibility = 'visible';
      await loadCourses();
    } catch (error) {
      reset();
    }
  }
  restoreSession();
})();
