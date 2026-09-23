(() => {
  const originalFetch = window.fetch.bind(window);
  let csrfCookieName = 'superchat_csrf';

  function readCookie(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    for (const part of document.cookie.split(';')) {
      const value = part.trim();
      if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
    }
    return null;
  }

  const authConfig = originalFetch('/auth/status', {
    headers: { 'Accept': 'application/json' },
  })
    .then((response) => response.ok ? response.json() : null)
    .then((data) => {
      if (data?.csrf_cookie_name) csrfCookieName = data.csrf_cookie_name;
      return data;
    })
    .catch(() => null);

  window.fetch = async (input, init = {}) => {
    const method = String(init.method || 'GET').toUpperCase();
    const unsafe = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);
    const target = new URL(typeof input === 'string' ? input : input.url, window.location.origin);
    const sameOrigin = target.origin === window.location.origin;
    let options = init;

    if (unsafe && sameOrigin && target.pathname !== '/auth/login') {
      await authConfig;
      const csrf = readCookie(csrfCookieName);
      if (csrf) {
        const headers = new Headers(init.headers || {});
        headers.set('X-CSRF-Token', csrf);
        options = { ...init, headers };
      }
    }

    const response = await originalFetch(input, options);
    if (response.status === 401 && target.pathname !== '/auth/login') {
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.replace(`/login?next=${encodeURIComponent(next)}`);
    }
    return response;
  };

  window.superchatLogout = async () => {
    try {
      await window.fetch('/auth/logout', {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
    } finally {
      window.location.replace('/login');
    }
  };
})();
