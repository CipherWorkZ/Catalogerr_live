// /static/js/api.js

// Grab apikey from query param (first-time login) and save it
(function initApiKey() {
  const urlParams = new URLSearchParams(window.location.search);
  const queryKey = urlParams.get("apikey");
  if (queryKey) {
    localStorage.setItem("apiKey", queryKey);
    // Clean the URL so apikey doesn’t stay visible
    window.history.replaceState({}, document.title, window.location.pathname);
  }
})();

// ✅ Centralized API fetch wrapper
async function apiFetch(url, options = {}) {
  const apiKey = localStorage.getItem("apiKey");
  if (!apiKey) {
    window.location.href = "/login";
    throw new Error("Missing API key");
  }

  options.headers = options.headers || {};
  if (!options.headers["X-Api-Key"]) {
    options.headers["X-Api-Key"] = apiKey;
  }

  const res = await fetch(url, options);

  if (res.status === 401 || res.status === 403) {
    alert("Session expired. Please log in again.");
    localStorage.removeItem("apiKey");
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  return res;
}
