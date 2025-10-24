// /static/js/api.js

window.activeStreams = [];

/**
 * Kill all active SSE streams (always run on logout / relogin)
 */
function closeAllStreams() {
  if (window.activeStreams?.length > 0) {
    window.activeStreams.forEach(es => es.close());
    window.activeStreams = [];
  }
}

/**
 * Open SSE stream with the stored API key
 */
function openStream(url, onMessage) {
  const apiKey = localStorage.getItem("apiKey");

  // If no key or reload in progress → don't open
  if (!apiKey || window.reloadingForNewKey) {
    console.warn("Skipping stream, no valid key yet");
    return;
  }

  const es = new EventSource(`${url}?api_key=${apiKey}`);
  es.onmessage = onMessage;
  window.activeStreams.push(es);
  return es;
}

/**
 * Handle ?apikey= after login
 */
(function initApiKey() {
  const urlParams = new URLSearchParams(window.location.search);
  const queryKey = urlParams.get("apikey");

  if (queryKey) {
    // 🚨 Always wipe the old key before setting new one
    localStorage.removeItem("apiKey");
    closeAllStreams();

    // Save the new key cleanly
    localStorage.setItem("apiKey", queryKey);

    // Flag reload to block any old calls during refresh
    window.reloadingForNewKey = true;

    // Reload without apikey in URL (fresh state)
    window.location.replace(window.location.pathname);
    return;
  }
})();

/**
 * Centralized API fetch wrapper
 */
async function apiFetch(url, options = {}) {
  const apiKey = localStorage.getItem("apiKey");
  if (!apiKey) {
    closeAllStreams();
    window.location.replace("/invalid_api");
    return;
  }

  options.headers ||= {};
  options.headers["X-Api-Key"] = apiKey;

  const res = await fetch(url, options);

  if (res.status === 401 || res.status === 403) {
    // 🚨 Key rejected → nuke everything
    localStorage.removeItem("apiKey");
    closeAllStreams();
    window.location.replace("/invalid_api");
    return;
  }

  return res;
}

/**
 * Optional: expose helpers globally
 */
window.apiFetch = apiFetch;
window.openStream = openStream;
window.closeAllStreams = closeAllStreams;
