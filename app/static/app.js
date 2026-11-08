(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const roleNames = { ADMIN: 'Quản trị viên', INSTRUCTOR: 'Giảng viên', STUDENT: 'Sinh viên' };
  // Reuse the token from the dedicated login page for this browser tab only.
  let token = sessionStorage.getItem('accessToken');
  let user = null;
  let expiryTimer;
  let reportVersion = 0;
  let currentCourse = null;
  let courseTab = 'materials';
  let activeTopic = null;
  const pages = ['home', 'courses', 'course', 'account', 'reports', 'admin'];
  const errorText = {
    UNAUTHENTICATED: 'Phiên đăng nhập đã hết hạn.',
    FORBIDDEN: 'Bạn không có quyền thực hiện.',
    NOT_FOUND: 'Không tìm thấy dữ liệu.',
    VALIDATION_ERROR: 'Dữ liệu chưa hợp lệ.',
    CONFLICT: 'Dữ liệu đã tồn tại.',
    INVALID_STATE: 'Trạng thái không cho phép thao tác này.',
    DEADLINE_PASSED: 'Đã quá hạn nộp.',
    COURSE_CODE_ALREADY_EXISTS: 'Mã khóa học đã tồn tại.',
    EMAIL_ALREADY_EXISTS: 'Email đã được sử dụng.',
    INVALID_CURRENT_PASSWORD: 'Mật khẩu hiện tại không đúng.',
    SERVER_ERROR: 'Lỗi máy chủ, vui lòng thử lại.'
  };
  const errText = error => errorText[error.message] || 'Thao tác thất bại (' + error.message + ').';

  // Tiny DOM builder: el('li', {class: 'x'}, child, 'text')
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === 'onclick' || key.startsWith('on')) node[key] = value;
      else if (key === 'class') node.className = value;
      else node.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined) continue;
      node.append(child.nodeType ? child : document.createTextNode(child));
    }
    return node;
  }
  const btn = (label, onclick, cls = 'link-btn') => el('button', { class: cls, type: 'button', onclick }, label);
  const fmtDate = iso => iso ? new Date(iso).toLocaleString('vi-VN') : '—';
  const fmtBytes = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';

  // Navigate between views without reloading or persisting the token.
  document.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    const url = new URL(link.href);
    if (url.origin !== location.origin) return;
    const known = ['/', '/home', '/account', '/reports', '/courses', '/course', '/admin'];
    if (!known.includes(url.pathname)) return;
    event.preventDefault();
    history.pushState({}, '', url.pathname + url.hash);
    showPage();
    if (url.hash) document.querySelector(url.hash)?.scrollIntoView();
    else window.scrollTo(0, 0);
  });

  function showPage() {
    const path = location.pathname;
    const page = path === '/account' ? 'account' : path === '/reports' ? 'reports'
      : path === '/courses' ? 'courses' : path === '/course' ? 'course'
      : path === '/admin' ? 'admin' : 'home';
    const names = { home: 'Trang chủ', courses: 'Khóa học', course: 'Chi tiết khóa học', account: 'Tài khoản', reports: 'Báo cáo điểm', admin: 'Quản trị' };
    pages.forEach(p => $(p + '-page').hidden = p !== page);
    $('breadcrumb').textContent = names[page];
    document.title = names[page] + ' · miniLMS';
    document.querySelectorAll('[data-page]').forEach(link => {
      const active = link.dataset.page === page;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (page === 'course' && !currentCourse) { history.replaceState({}, '', '/courses'); return showPage(); }
    if (page === 'home' && user) loadCourses();
    if (page === 'courses' && user) loadCoursesPage();
    if (page === 'course' && user) renderCourseTab(courseTab);
    if (page === 'account' && user) loadAccount();
    if (page === 'admin' && user) loadAdmin();
  }
  window.addEventListener('popstate', showPage);

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
      if (response.status === 401 && path !== '/auth/logout') reset();
      throw new Error(data.error || 'SERVER_ERROR');
    }
    return data;
  }
  async function download(url, filename) {
    const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new Error('SERVER_ERROR');
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = el('a', { href: objectUrl, download: filename });
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }

  // ── Home & reports (existing behaviour) ───────────────────────────
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
    const box = el('div', { class: 'empty-state' },
      el('span', { 'aria-hidden': 'true' }, '▤'),
      el('div', {}, el('h3', {}, title), el('p', {}, description)));
    $('course-grid').replaceChildren(box);
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
        const cover = el('div', { class: 'course-cover' + (index % 2 ? ' database' : '') },
          el('b', {}, index % 2 ? '{ db }' : '</>'),
          el('span', {}, course.id.toUpperCase()));
        const result = el('div', { class: 'course-result' },
          el('span', {}, 'Điểm học tập'),
          el('strong', {}, course.score === null ? 'Chưa có điểm cá nhân' : `${course.score.toLocaleString('vi-VN')} / 10`));
        const body = el('div', { class: 'course-body' },
          el('h3', {}, course.title),
          el('p', {}, 'Giảng viên · ' + course.instructor),
          result);
        const card = el('article', { class: 'course-card' }, cover, body);
        card.style.cursor = 'pointer';
        card.onclick = () => openCourse({ id: course.id, title: course.title });
        $('course-grid').append(card);
      });
    } catch (error) {
      if (user) { $('home-message').textContent = 'Không tải được khóa học. Vui lòng thử lại.'; $('report-message').textContent = 'Không tải được danh sách khóa học. Vui lòng thử lại ở trang chủ.'; empty('Kết nối bị gián đoạn', 'Bạn có thể thử tải lại danh sách.'); const retry = document.createElement('button'); retry.className = 'button outline'; retry.textContent = 'Thử lại'; retry.onclick = loadCourses; $('course-grid').append(retry); }
    }
  }

  // ── Courses page ──────────────────────────────────────────────────
  let courseSearchTimer;
  $('course-search').addEventListener('input', () => {
    clearTimeout(courseSearchTimer);
    courseSearchTimer = setTimeout(loadCoursesPage, 250);
  });
  $('enroll-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const enrollment = await api('/courses/enroll', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: $('enroll-code').value.trim() }) });
      $('courses-message').textContent = 'Đã ghi danh vào khóa học.';
      $('enroll-code').value = '';
      loadCoursesPage();
    } catch (error) { $('courses-message').textContent = errText(error); }
  });
  $('create-course-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      await api('/courses', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: $('new-course-title').value.trim(), code: $('new-course-code').value.trim() }) });
      $('courses-message').textContent = 'Đã tạo khóa học.';
      $('new-course-title').value = ''; $('new-course-code').value = '';
      loadCoursesPage();
    } catch (error) { $('courses-message').textContent = errText(error); }
  });
  async function loadCoursesPage() {
    const q = $('course-search').value.trim();
    $('courses-message').textContent = 'Đang tải…';
    try {
      const rows = await api('/api/courses' + (q ? '?q=' + encodeURIComponent(q) : ''));
      $('courses-message').textContent = '';
      const list = $('course-list');
      list.replaceChildren();
      if (!rows.length) { list.append(el('li', { class: 'meta' }, el('b', {}, 'Không có khóa học.'), el('small', {}, 'Thử từ khóa khác hoặc ghi danh bằng mã.'))); return; }
      rows.forEach(course => {
        list.append(el('li', {},
          el('div', { class: 'meta' },
            el('b', {}, course.title),
            el('small', {}, 'Mã: ' + (course.code || '—'))),
          el('div', { class: 'item-actions' }, btn('Mở ↗', () => openCourse(course), 'button outline'))));
      });
    } catch (error) { $('courses-message').textContent = errText(error); }
  }
  function openCourse(course) {
    currentCourse = course;
    courseTab = 'materials';
    activeTopic = null;
    $('course-title').textContent = course.title;
    $('course-sub').textContent = 'Mã: ' + (course.code || '—');
    history.pushState({}, '', '/course');
    showPage();
  }

  // ── Course detail tabs ────────────────────────────────────────────
  $('course-tabs').addEventListener('click', event => {
    const tab = event.target.closest('.tab-btn');
    if (!tab) return;
    courseTab = tab.dataset.tab;
    renderCourseTab(courseTab);
  });
  function renderCourseTab(tab) {
    document.querySelectorAll('#course-tabs .tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    ['materials', 'assignments', 'quizzes', 'forum', 'announcements', 'members'].forEach(t => $('tab-' + t).hidden = t !== tab);
    if (!currentCourse) return;
    const cid = currentCourse.id;
    const isTeacher = user && (user.role === 'INSTRUCTOR' || user.role === 'ADMIN');
    if (tab === 'materials') loadMaterials(cid, isTeacher);
    if (tab === 'assignments') loadAssignments(cid, isTeacher);
    if (tab === 'quizzes') loadQuizzes(cid, isTeacher);
    if (tab === 'forum') activeTopic ? renderTopic(activeTopic) : loadTopics(cid);
    if (tab === 'announcements') loadAnnouncements(cid, isTeacher);
    if (tab === 'members') loadMembers(cid, isTeacher);
  }

  // Materials
  $('material-form').addEventListener('submit', async event => {
    event.preventDefault();
    const file = $('material-file').files[0];
    if (!file) return;
    const body = new FormData(); body.append('file', file);
    try {
      await api(`/courses/${currentCourse.id}/materials`, { method: 'POST', body });
      $('material-file').value = '';
      $('materials-message').textContent = 'Đã tải lên.';
      loadMaterials(currentCourse.id, true);
    } catch (error) { $('materials-message').textContent = errText(error); }
  });
  async function loadMaterials(cid, isTeacher) {
    $('material-form').hidden = !isTeacher;
    $('materials-message').textContent = 'Đang tải…';
    try {
      const rows = await api(`/courses/${cid}/materials`);
      $('materials-message').textContent = '';
      const list = $('material-list'); list.replaceChildren();
      if (!rows.length) { list.append(el('li', { class: 'meta' }, el('b', {}, 'Chưa có tài liệu.'))); return; }
      rows.forEach(m => {
        const actions = el('div', { class: 'item-actions' },
          btn('Tải xuống', () => download(m.downloadUrl, m.originalName).catch(e => $('materials-message').textContent = errText(e))));
        if (isTeacher) actions.append(btn('Xóa', async () => {
          try { await api(`/materials/${m.id}`, { method: 'DELETE' }); loadMaterials(cid, isTeacher); }
          catch (error) { $('materials-message').textContent = errText(error); }
        }));
        list.append(el('li', {},
          el('div', { class: 'meta' }, el('b', {}, m.originalName), el('small', {}, fmtBytes(m.sizeBytes) + ' · ' + fmtDate(m.createdAt))),
          actions));
      });
    } catch (error) { $('materials-message').textContent = errText(error); }
  }

  // Assignments
  $('assignment-form').addEventListener('submit', async event => {
    event.preventDefault();
    const due = new Date($('assignment-due').value);
    if (isNaN(due)) { $('assignments-message').textContent = 'Chọn hạn nộp hợp lệ.'; return; }
    try {
      await api(`/courses/${currentCourse.id}/assignments`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: $('assignment-title').value.trim(), dueAt: due.toISOString() })
      });
      $('assignment-title').value = ''; $('assignment-due').value = '';
      $('assignments-message').textContent = 'Đã tạo bài tập.';
      loadAssignments(currentCourse.id, true);
    } catch (error) { $('assignments-message').textContent = errText(error); }
  });
  async function loadAssignments(cid, isTeacher) {
    $('assignment-form').hidden = !isTeacher;
    $('assignments-message').textContent = 'Đang tải…';
    const area = $('assignment-list'); area.replaceChildren();
    let assignments;
    try { assignments = await api(`/courses/${cid}/assignments`); $('assignments-message').textContent = ''; }
    catch (error) { $('assignments-message').textContent = errText(error); return; }
    if (!assignments.length) { area.append(el('p', {}, 'Chưa có bài tập.')); return; }
    for (const a of assignments) {
      const card = el('div', { class: 'quiz-question' },
        el('h4', {}, a.title + ' — hạn nộp ' + fmtDate(a.dueAt)),
        a.description ? el('p', {}, a.description) : null);
      const subsBox = el('ul', { class: 'sub-list' });
      if (!isTeacher) {
        const file = el('input', { type: 'file', required: 'required' });
        card.append(el('form', { class: 'inline-form', onsubmit: async event => {
          event.preventDefault();
          if (!file.files[0]) return;
          const body = new FormData(); body.append('file', file.files[0]);
          try {
            await api(`/courses/${cid}/assignments/${a.id}/submissions`, { method: 'POST', body });
            $('assignments-message').textContent = 'Đã nộp bài.';
            loadAssignments(cid, false);
          } catch (error) { $('assignments-message').textContent = errText(error); }
        } }, file, el('button', { class: 'button green', type: 'submit' }, 'Nộp bài')));
      }
      card.append(btn('Xem bài nộp ▾', async () => {
        if (subsBox.childElementCount) { subsBox.replaceChildren(); return; }
        try {
          const subs = await api(`/courses/${cid}/assignments/${a.id}/submissions`);
          if (!subs.length) { subsBox.append(el('li', {}, 'Chưa có bài nộp.')); }
          subs.forEach(s => {
            const li = el('li', {},
              el('span', {}, (s.studentId === user.id ? 'Bạn' : s.studentId) + ' · ' + (s.originalName || '—') +
                ' · ' + (s.score === null ? 'Chưa chấm' : s.score + '/10' + (s.feedback ? ' · "' + s.feedback + '"' : ''))),
              btn('Tải xuống', () => download(s.downloadUrl, s.originalName)));
            if (isTeacher) {
              const score = el('input', { type: 'number', min: '0', max: '10', step: '0.1', value: s.score ?? '', placeholder: 'Điểm' });
              const feedback = el('input', { type: 'text', value: s.feedback || '', placeholder: 'Nhận xét', maxlength: '1000' });
              li.append(el('button', { class: 'button outline', type: 'button', onclick: async () => {
                try {
                  await api(`/courses/${cid}/assignments/${a.id}/submissions/${s.studentId}/grade`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ score: Number(score.value), feedback: feedback.value })
                  });
                  $('assignments-message').textContent = 'Đã chấm ' + s.studentId + '.';
                  loadAssignments(cid, isTeacher);
                } catch (error) { $('assignments-message').textContent = errText(error); }
              } }, 'Chấm'));
              li.append(score, feedback);
            }
            subsBox.append(li);
          });
        } catch (error) { $('assignments-message').textContent = errText(error); }
      }), subsBox);
      area.append(card);
    }
  }

  // Quizzes
  $('quiz-form').addEventListener('submit', async event => {
    event.preventDefault();
    const questions = [...document.querySelectorAll('.q-editor')].map(block => {
      const options = [...block.querySelectorAll('.q-opt input[type=text]')].map(i => i.value.trim()).filter(Boolean);
      const correct = [...block.querySelectorAll('.q-opt input[type=radio]')].findIndex(r => r.checked);
      return { text: block.querySelector('.q-text').value.trim(), options, answerIndex: correct, points: Number(block.querySelector('.q-points').value) || 1 };
    }).filter(q => q.text && q.options.length >= 2 && q.answerIndex >= 0);
    if (!questions.length) { $('quizzes-message').textContent = 'Cần ít nhất 1 câu hỏi hoàn chỉnh (2 lựa chọn + chọn đáp án đúng).'; return; }
    try {
      await api(`/courses/${currentCourse.id}/quizzes`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: $('quiz-title').value.trim(), timeMinutes: Number($('quiz-minutes').value) || 30, questions })
      });
      $('quizzes-message').textContent = 'Đã tạo bài kiểm tra.';
      $('quiz-title').value = '';
      loadQuizzes(currentCourse.id, true);
    } catch (error) { $('quizzes-message').textContent = errText(error); }
  });
  // Minimal dynamic question editor for the create form.
  $('quiz-form').append(el('div', { id: 'q-editors' }));
  const addQuestionEditor = () => {
    const block = el('div', { class: 'q-editor quiz-question' });
    block.append(el('input', { class: 'q-text', type: 'text', placeholder: 'Nội dung câu hỏi', required: 'required' }));
    const opts = el('div', { class: 'q-opts' });
    const radioName = 'q' + Date.now() + Math.random();
    const addOption = checked => {
      const row = el('label', { class: 'q-opt' },
        el('input', { type: 'radio', name: radioName, ...(checked ? { checked: 'checked' } : {}) }),
        el('input', { type: 'text', placeholder: 'Lựa chọn' }));
      opts.append(row);
    };
    addOption(true); addOption(false);
    block.append(opts,
      el('div', { class: 'grade-row' },
        el('label', {}, 'Điểm ', el('input', { class: 'q-points', type: 'number', min: '1', max: '10', value: '1' })),
        btn('+ Lựa chọn', () => addOption(false)),
        btn('× Bỏ câu hỏi', () => block.remove())));
    $('q-editors').append(block);
  };
  addQuestionEditor();
  $('quiz-form').append(btn('+ Thêm câu hỏi', addQuestionEditor, 'button outline'));
  async function loadQuizzes(cid, isTeacher) {
    $('quiz-form').hidden = !isTeacher;
    $('quizzes-message').textContent = 'Đang tải…';
    const area = $('quiz-list'); area.replaceChildren();
    let quizzes;
    try { quizzes = await api(`/courses/${cid}/quizzes`); $('quizzes-message').textContent = ''; }
    catch (error) { $('quizzes-message').textContent = errText(error); return; }
    if (!quizzes.length) { area.append(el('p', {}, 'Chưa có bài kiểm tra.')); return; }
    quizzes.forEach(qz => {
      const card = el('div', { class: 'quiz-question' },
        el('h4', {}, qz.title + ' · ' + qz.timeMinutes + ' phút'));
      const box = el('div', {});
      card.append(btn(isTeacher ? 'Xem lượt làm bài ▾' : 'Làm bài ↗', () => isTeacher ? renderAttemptsList(cid, qz, box) : startQuiz(cid, qz, box)), box);
      area.append(card);
    });
  }
  async function renderAttemptsList(cid, qz, box) {
    if (box.childElementCount) { box.replaceChildren(); return; }
    try {
      const attempts = await api(`/courses/${cid}/quizzes/${qz.id}/attempts`);
      if (!attempts.length) { box.append(el('p', {}, 'Chưa có lượt làm bài.')); return; }
      const list = el('ul', { class: 'sub-list' });
      attempts.forEach(at => {
        const li = el('li', {},
          el('span', {}, at.studentId + ' · ' + at.state + (at.score !== null && at.score !== undefined ? ' · ' + at.score + '/10' : '')));
        if (at.state === 'SUBMITTED') {
          const score = el('input', { type: 'number', min: '0', max: '10', step: '0.1', value: at.score ?? '', placeholder: 'Điểm' });
          li.append(score, el('button', { class: 'button outline', type: 'button', onclick: async () => {
            try {
              await api(`/courses/${cid}/quizzes/${qz.id}/attempts/${at.studentId}/grade`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ score: Number(score.value) })
              });
              $('quizzes-message').textContent = 'Đã chấm ' + at.studentId + '.';
              box.replaceChildren(); renderAttemptsList(cid, qz, box);
            } catch (error) { $('quizzes-message').textContent = errText(error); }
          } }, 'Chấm'));
        }
        list.append(li);
      });
      box.append(list);
    } catch (error) { $('quizzes-message').textContent = errText(error); }
  }
  async function startQuiz(cid, qz, box) {
    if (box.childElementCount) { box.replaceChildren(); return; }
    try {
      const detail = await api(`/courses/${cid}/quizzes/${qz.id}`);
      let attempt;
      try { attempt = await api(`/courses/${cid}/quizzes/${qz.id}/attempts`, { method: 'POST' }); }
      catch (error) {
        if (error.message !== 'CONFLICT' && error.message !== 'INVALID_STATE') throw error;
        const mine = await api(`/courses/${cid}/quizzes/${qz.id}/attempts?studentId=` + encodeURIComponent(user.id));
        attempt = mine.find(a => a.studentId === user.id) || mine[0];
      }
      if (attempt.state !== 'IN_PROGRESS') {
        box.append(el('p', {}, 'Bạn đã nộp bài. Trạng thái: ' + attempt.state + (attempt.score !== null && attempt.score !== undefined ? ' · Điểm ' + attempt.score + '/10' : '') + '.'));
        return;
      }
      const picks = new Array(detail.questions.length).fill(null);
      const form = el('form', { onsubmit: async event => {
        event.preventDefault();
        const answers = detail.questions.map((q, i) => picks[i] === null ? '' : String.fromCharCode(65 + picks[i])).join(',');
        try {
          const result = await api(`/courses/${cid}/quizzes/${qz.id}/attempts/submit`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers })
          });
          box.replaceChildren(el('p', {}, 'Đã nộp bài. Điểm tự động: ' + (result.score === null || result.score === undefined ? '—' : result.score) + '/10.'));
          $('quizzes-message').textContent = '';
        } catch (error) { $('quizzes-message').textContent = errText(error); }
      } });
      form.append(el('p', {}, 'Hạn nộp: ' + fmtDate(attempt.deadline)));
      detail.questions.forEach((q, i) => {
        const block = el('div', { class: 'quiz-question' }, el('h4', {}, `Câu ${i + 1} (${q.points} điểm). ` + q.text));
        q.options.forEach((opt, oi) => {
          block.append(el('label', {},
            el('input', { type: 'radio', name: 'q' + i, onchange: () => { picks[i] = oi; } }),
            ' ' + String.fromCharCode(65 + oi) + '. ' + opt));
        });
        form.append(block);
      });
      form.append(
        btn('Lưu tạm', async () => {
          const answers = detail.questions.map((q, i) => picks[i] === null ? '' : String.fromCharCode(65 + picks[i])).join(',');
          try {
            await api(`/courses/${cid}/quizzes/${qz.id}/attempts/answers`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers }) });
            $('quizzes-message').textContent = 'Đã lưu câu trả lời tạm thời.';
          } catch (error) { $('quizzes-message').textContent = errText(error); }
        }, 'button outline'),
        el('button', { class: 'button green', type: 'submit' }, 'Nộp bài'));
      box.replaceChildren(form);
    } catch (error) { $('quizzes-message').textContent = errText(error); }
  }

  // Forum
  $('topic-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      await api(`/courses/${currentCourse.id}/topics`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: $('topic-title').value.trim(), body: $('topic-body').value.trim() })
      });
      $('topic-title').value = ''; $('topic-body').value = '';
      $('forum-message').textContent = 'Đã đăng chủ đề.';
      activeTopic = null;
      loadTopics(currentCourse.id);
    } catch (error) { $('forum-message').textContent = errText(error); }
  });
  async function loadTopics(cid) {
    $('forum-message').textContent = 'Đang tải…';
    const area = $('forum-area'); area.replaceChildren();
    try {
      const rows = await api(`/courses/${cid}/topics`);
      $('forum-message').textContent = '';
      if (!rows.length) { area.append(el('p', {}, 'Chưa có chủ đề. Hãy khởi động thảo luận.')); return; }
      const list = el('ul', { class: 'item-list' });
      rows.forEach(t => {
        const actions = el('div', { class: 'item-actions' }, btn('Mở ↗', () => { activeTopic = t; renderTopic(t); }));
        if (t.authorId === user.id) actions.append(
          btn('Sửa', () => editPost(`/topics/${t.id}`, { title: t.title, body: t.body }, () => loadTopics(cid))),
          btn('Xóa', async () => {
            try { await api(`/topics/${t.id}`, { method: 'DELETE' }); loadTopics(cid); }
            catch (error) { $('forum-message').textContent = errText(error); }
          }));
        list.append(el('li', {},
          el('div', { class: 'meta' }, el('b', {}, t.title), el('small', {}, (t.commentCount || 0) + ' bình luận · ' + fmtDate(t.createdAt))),
          actions));
      });
      area.append(list);
    } catch (error) { $('forum-message').textContent = errText(error); }
  }
  function editPost(url, current, done) {
    const title = current.title !== undefined ? el('input', { type: 'text', value: current.title }) : null;
    const body = el('input', { type: 'text', value: current.body || '' });
    const form = el('form', { class: 'inline-form', onsubmit: async event => {
      event.preventDefault();
      const payload = { body: body.value.trim() };
      if (title) payload.title = title.value.trim();
      try { await api(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); done(); }
      catch (error) { $('forum-message').textContent = errText(error); }
    } }, title, body,
      el('button', { class: 'button green', type: 'submit' }, 'Lưu'), btn('Hủy', done));
    $('forum-area').prepend(el('div', { class: 'quiz-question' }, el('h4', {}, 'Chỉnh sửa'), form));
  }
  async function renderTopic(topic) {
    const area = $('forum-area'); area.replaceChildren();
    const comments = el('ul', { class: 'item-list' });
    const load = async () => {
      comments.replaceChildren();
      try {
        const rows = await api(`/topics/${topic.id}/comments`);
        if (!rows.length) comments.append(el('li', { class: 'meta' }, el('b', {}, 'Chưa có bình luận.')));
        rows.forEach(c => {
          const actions = el('div', { class: 'item-actions' });
          if (c.authorId === user.id) actions.append(
            btn('Sửa', () => {
              const input = el('input', { type: 'text', value: c.body });
              comments.prepend(el('li', { class: 'quiz-question' }, el('h4', {}, 'Sửa bình luận'), input,
                el('button', { class: 'button green', type: 'button', onclick: async () => {
                  try { await api(`/comments/${c.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body: input.value.trim() }) }); load(); }
                  catch (error) { $('forum-message').textContent = errText(error); }
                } }, 'Lưu')));
            }),
            btn('Xóa', async () => {
              try { await api(`/comments/${c.id}`, { method: 'DELETE' }); load(); }
              catch (error) { $('forum-message').textContent = errText(error); }
            }));
          comments.append(el('li', {},
            el('div', { class: 'meta' }, el('b', {}, c.authorId), el('small', {}, fmtDate(c.createdAt))),
            actions));
        });
      } catch (error) { $('forum-message').textContent = errText(error); }
    };
    const commentInput = el('input', { type: 'text', placeholder: 'Viết bình luận…', required: 'required' });
    area.append(
      el('div', { class: 'quiz-question' },
        el('h4', {}, topic.title),
        el('p', {}, topic.body),
        el('div', { class: 'item-actions' },
          btn('← Danh sách chủ đề', () => { activeTopic = null; loadTopics(currentCourse.id); }),
          topic.authorId === user.id ? btn('Sửa', () => editPost(`/topics/${topic.id}`, { title: topic.title, body: topic.body }, () => { activeTopic = null; loadTopics(currentCourse.id); })) : null,
          topic.authorId === user.id ? btn('Xóa', async () => {
            try { await api(`/topics/${topic.id}`, { method: 'DELETE' }); activeTopic = null; loadTopics(currentCourse.id); }
            catch (error) { $('forum-message').textContent = errText(error); }
          }) : null)),
      el('form', { class: 'inline-form', onsubmit: async event => {
        event.preventDefault();
        try { await api(`/topics/${topic.id}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body: commentInput.value.trim() }) }); commentInput.value = ''; load(); }
        catch (error) { $('forum-message').textContent = errText(error); }
      } }, commentInput, el('button', { class: 'button green', type: 'submit' }, 'Bình luận')),
      comments);
    load();
  }

  // Announcements
  $('announcement-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      await api(`/courses/${currentCourse.id}/announcements`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: $('announcement-title').value.trim(), body: $('announcement-body').value.trim() })
      });
      $('announcement-title').value = ''; $('announcement-body').value = '';
      $('announcements-message').textContent = 'Đã phát thông báo (email queued ở chế độ lab).';
      loadAnnouncements(currentCourse.id, true);
    } catch (error) { $('announcements-message').textContent = errText(error); }
  });
  async function loadAnnouncements(cid, isTeacher) {
    $('announcement-form').hidden = !isTeacher;
    $('announcements-message').textContent = 'Đang tải…';
    const list = $('announcement-list'); list.replaceChildren();
    try {
      const rows = await api(`/courses/${cid}/announcements`);
      $('announcements-message').textContent = '';
      if (!rows.length) { list.append(el('li', { class: 'meta' }, el('b', {}, 'Chưa có thông báo.'))); return; }
      rows.forEach(n => list.append(el('li', {},
        el('div', { class: 'meta' }, el('b', {}, n.title), el('small', {}, n.body + ' · ' + fmtDate(n.createdAt))))));
    } catch (error) { $('announcements-message').textContent = errText(error); }
  }

  // Members
  $('add-student-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      await api(`/courses/${currentCourse.id}/students`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ studentId: $('add-student-id').value.trim() })
      });
      $('add-student-id').value = '';
      $('members-message').textContent = 'Đã thêm sinh viên.';
      loadMembers(currentCourse.id, true);
    } catch (error) { $('members-message').textContent = errText(error); }
  });
  async function loadMembers(cid, isTeacher) {
    $('add-student-form').hidden = !isTeacher;
    $('members-message').textContent = 'Đang tải…';
    const list = $('member-list'); list.replaceChildren();
    try {
      const rows = await api('/members?courseId=' + encodeURIComponent(cid));
      $('members-message').textContent = '';
      if (!rows.length) { list.append(el('li', { class: 'meta' }, el('b', {}, 'Chưa có thành viên.'))); return; }
      rows.forEach(m => {
        const photo = m.avatarUrl ? el('img', { src: m.avatarUrl, alt: '', class: 'avatar small' }) : null;
        list.append(el('li', {},
          el('div', { class: 'meta' }, photo, el('b', {}, (m.fullName || m.email) + (m.fullName ? '· ' + m.email : '')), el('small', {}, roleNames[m.role] || m.role))));
      });
    } catch (error) { $('members-message').textContent = errText(error); }
  }

  // ── Account page ──────────────────────────────────────────────────
  function applyAvatar(u) {
    const photo = $('profile-photo');
    if (u.avatarUrl) { photo.src = u.avatarUrl; photo.hidden = false; $('profile-avatar').hidden = true; }
    else { photo.hidden = true; $('profile-avatar').hidden = false; $('profile-avatar').textContent = u.email[0].toUpperCase(); }
    $('header-avatar').textContent = u.email[0].toUpperCase();
  }
  function loadAccount() {
    $('profile-fullname').value = user.fullName || '';
    $('profile-phone').value = user.phone || '';
    $('profile-bio').value = user.bio || '';
  }
  $('profile-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      user = await api('/me', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fullName: $('profile-fullname').value.trim(), phone: $('profile-phone').value.trim(), bio: $('profile-bio').value.trim() })
      });
      $('account-message').textContent = 'Đã lưu hồ sơ.';
    } catch (error) { $('account-message').textContent = errText(error); }
  });
  $('avatar-form').addEventListener('submit', async event => {
    event.preventDefault();
    const file = $('avatar-file').files[0];
    if (!file) { $('account-message').textContent = 'Chọn một tệp ảnh trước.'; return; }
    const body = new FormData(); body.append('avatar', file);
    try {
      const result = await api('/me/avatar', { method: 'POST', body });
      user = await api('/me');
      applyAvatar(user);
      $('avatar-file').value = '';
      $('account-message').textContent = 'Đã đổi ảnh đại diện.';
    } catch (error) { $('account-message').textContent = errText(error); }
  });
  $('password-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      await api('/auth/change-password', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ currentPassword: $('pw-current').value, newPassword: $('pw-new').value })
      });
      $('pw-current').value = ''; $('pw-new').value = '';
      $('account-message').textContent = 'Đã đổi mật khẩu. Vui lòng đăng nhập lại.';
      setTimeout(reset, 1500);
    } catch (error) { $('account-message').textContent = errText(error); }
  });
  $('logout').addEventListener('click', async () => {
    try { await api('/auth/logout', { method: 'POST' }); } catch (error) { /* token may already be gone */ }
    reset();
  });

  // ── Admin page ────────────────────────────────────────────────────
  let adminSearchTimer;
  $('admin-user-search').addEventListener('input', () => {
    clearTimeout(adminSearchTimer);
    adminSearchTimer = setTimeout(loadAdminUsers, 250);
  });
  async function loadAdminUsers() {
    const q = $('admin-user-search').value.trim();
    const body = $('admin-users').tBodies[0]; body.replaceChildren();
    try {
      const rows = await api('/admin/users' + (q ? '?q=' + encodeURIComponent(q) : ''));
      rows.forEach(u => {
        const role = el('select', { onchange: async e => {
          try { await api(`/admin/users/${u.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: e.target.value }) }); $('admin-message').textContent = 'Đã cập nhật vai trò.'; }
          catch (error) { $('admin-message').textContent = errText(error); loadAdminUsers(); }
        } }, ...['ADMIN', 'INSTRUCTOR', 'STUDENT'].map(r => el('option', { value: r, ...(r === u.role ? { selected: 'selected' } : {}) }, roleNames[r])));
        const lock = btn(u.locked ? 'Mở khóa' : 'Khóa tài khoản', async () => {
          try { await api(`/admin/users/${u.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ locked: !u.locked }) }); loadAdminUsers(); }
          catch (error) { $('admin-message').textContent = errText(error); }
        }, 'button outline');
        body.append(el('tr', {},
          el('td', {}, u.email), el('td', {}, u.fullName || '—'), el('td', {}, role),
          el('td', {}, u.locked ? 'Đã khóa' : 'Hoạt động'), el('td', {}, lock)));
      });
    } catch (error) { $('admin-message').textContent = errText(error); }
  }
  async function loadAdmin() {
    loadAdminUsers();
    const courseBody = $('admin-courses').tBodies[0]; courseBody.replaceChildren();
    try {
      const rows = await api('/api/courses');
      rows.forEach(c => courseBody.append(el('tr', {},
        el('td', {}, c.code || c.id), el('td', {}, c.title),
        el('td', {}, btn('Xóa', async () => {
          try { await api(`/admin/courses/${c.id}`, { method: 'DELETE' }); loadAdmin(); }
          catch (error) { $('admin-message').textContent = errText(error); }
        })))));
    } catch (error) { $('admin-message').textContent = errText(error); }
    const auditBody = $('admin-audit').tBodies[0]; auditBody.replaceChildren();
    try {
      const rows = await api('/admin/audit?limit=50');
      if (!rows.length) auditBody.append(el('tr', {}, el('td', { colspan: '5' }, 'Chưa có nhật ký.')));
      rows.forEach(entry => auditBody.append(el('tr', {},
        el('td', {}, fmtDate(entry.ts)), el('td', {}, entry.action || '—'),
        el('td', {}, entry.actorId || '—'), el('td', {}, entry.resource || '—'),
        el('td', {}, entry.result || '—'))));
    } catch (error) { /* audit table stays empty on error */ }
  }

  // ── Session bootstrap ─────────────────────────────────────────────
  async function restoreSession() {
    const expiresAt = Number(sessionStorage.getItem('accessTokenExpiresAt'));
    if (!token || !Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      reset();
      return;
    }
    try {
      user = await api('/me');
      $('header-name').textContent = user.email;
      $('profile-title').textContent = (user.fullName || user.email.split('@')[0]);
      $('profile-email').textContent = user.email;
      $('profile-id').textContent = user.id;
      $('profile-role-detail').textContent = $('profile-role').textContent = $('role-stat').textContent = roleNames[user.role] || user.role;
      applyAvatar(user);
      $('enroll-form').hidden = user.role !== 'STUDENT';
      $('create-course-form').hidden = user.role === 'STUDENT';
      $('nav-admin').hidden = user.role !== 'ADMIN';

      expiryTimer = setTimeout(reset, Math.min(expiresAt - Date.now(), 2147483647));
      document.documentElement.style.visibility = 'visible';
      showPage();
    } catch (error) {
      reset();
    }
  }
  restoreSession();
})();
