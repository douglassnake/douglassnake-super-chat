(() => {
  const originalFetch = window.fetch.bind(window);

  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (response.status === 401) {
      const target = `${window.location.pathname}${window.location.search}`;
      window.location.replace(`/login?next=${encodeURIComponent(target)}`);
    }
    return response;
  };

  window.superchatLogout = async () => {
    try {
      await originalFetch('/auth/logout', {
        method: 'POST',
        headers: { 'Accept': 'application/json' },
      });
    } finally {
      window.location.replace('/login');
    }
  };
})();
