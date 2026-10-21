const form = document.querySelector('#auth-form');
const message = document.querySelector('#form-message');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  message.textContent = '';
  message.className = 'message';
  const data = Object.fromEntries(new FormData(form));
  const endpoint = form.dataset.mode === 'login' ? '/auth/login' : '/auth/register';

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'REQUEST_FAILED');
    if (form.dataset.mode === 'login') {
      sessionStorage.setItem('accessToken', result.accessToken);
      message.textContent = 'Đăng nhập thành công. Bạn có thể tiếp tục học tập.';
      message.className = 'message success';
    } else {
      window.location.href = '/login?registered=1';
    }
  } catch (error) {
    const errors = {
      INVALID_CREDENTIALS: 'Email hoặc mật khẩu không chính xác.',
      ACCOUNT_LOCKED: 'Tài khoản tạm khóa. Vui lòng thử lại sau 15 phút.',
      EMAIL_ALREADY_EXISTS: 'Email này đã được đăng ký.',
      PASSWORD_MISMATCH: 'Mật khẩu nhập lại không khớp.',
      VALIDATION_ERROR: 'Vui lòng kiểm tra lại thông tin.'
    };
    message.textContent = errors[error.message] || 'Không thể thực hiện. Vui lòng thử lại.';
    message.className = 'message error';
  }
});
