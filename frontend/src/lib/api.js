/**
 * API client.
 *
 * The access token lives in this module's memory only — never in localStorage,
 * where any XSS payload could read it. Durable sign-in comes from the HttpOnly
 * refresh cookie the server sets, which JavaScript cannot touch: on boot, and
 * whenever a request comes back 401, the client silently exchanges that cookie
 * for a new access token and replays the request once.
 */

const BASE = "/api";

let accessToken = null;
let refreshPromise = null;
let onSessionLost = null;

export function setAccessToken(token) {
  accessToken = token || null;
}

export function getAccessToken() {
  return accessToken;
}

/** Called when the refresh cookie is gone or rejected, so the UI can sign out. */
export function onUnauthenticated(handler) {
  onSessionLost = handler;
}

export class ApiError extends Error {
  constructor(message, { status, code, fields } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields || null;
  }

  /** A readable message for a given form field, if the server flagged one. */
  fieldError(path) {
    if (!this.fields) return null;
    const segments = path.split(".");
    let node = this.fields;
    for (const segment of segments) {
      if (node == null) return null;
      node = node[segment];
    }
    if (!node) return null;
    return Array.isArray(node) ? node.join(" ") : String(node);
  }
}

async function parseBody(response) {
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function errorFrom(response, body) {
  const message =
    body?.detail ||
    (response.status >= 500
      ? "The server had a problem. Please try again."
      : "That request could not be completed.");
  return new ApiError(message, {
    status: response.status,
    code: body?.code,
    fields: body?.fields,
  });
}

/**
 * Exchange the refresh cookie for a fresh access token.
 *
 * Concurrent callers share one in-flight request, so a burst of 401s does not
 * fire a burst of refreshes (which token rotation would reject anyway).
 */
export function refreshAccessToken() {
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const response = await fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    });
    const body = await parseBody(response);
    if (!response.ok) {
      accessToken = null;
      throw errorFrom(response, body);
    }
    accessToken = body.access;
    return body;
  })().finally(() => {
    refreshPromise = null;
  });

  return refreshPromise;
}

async function send(path, { method = "GET", body, isForm = false, signal, _retried = false } = {}) {
  const headers = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    credentials: "same-origin",
    signal,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });

  // A 401 on a token we were holding usually just means it expired: refresh
  // once and replay. Auth endpoints are excluded to avoid a refresh loop.
  if (response.status === 401 && !_retried && !path.startsWith("/auth/")) {
    try {
      await refreshAccessToken();
    } catch {
      onSessionLost?.();
      throw errorFrom(response, await parseBody(response));
    }
    return send(path, { method, body, isForm, signal, _retried: true });
  }

  const parsed = await parseBody(response);
  if (!response.ok) throw errorFrom(response, parsed);
  return parsed;
}

export const api = {
  get: (path, options) => send(path, { ...options, method: "GET" }),
  post: (path, body, options) => send(path, { ...options, method: "POST", body }),
  patch: (path, body, options) => send(path, { ...options, method: "PATCH", body }),
  delete: (path, options) => send(path, { ...options, method: "DELETE" }),
};

/**
 * Upload a file with real progress.
 *
 * `fetch` cannot report upload progress, so this one call uses XMLHttpRequest.
 * Returns an object carrying the promise plus an `abort()` so the UI can cancel.
 */
export function uploadVideo(file, { onProgress } = {}) {
  const request = new XMLHttpRequest();

  const promise = new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);

    request.open("POST", `${BASE}/videos/`);
    request.withCredentials = true;
    if (accessToken) request.setRequestHeader("Authorization", `Bearer ${accessToken}`);

    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });

    request.addEventListener("load", () => {
      let body = null;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        body = null;
      }
      if (request.status >= 200 && request.status < 300) {
        resolve(body);
        return;
      }
      reject(
        new ApiError(body?.detail || "The upload failed.", {
          status: request.status,
          code: body?.code,
          fields: body?.fields,
        }),
      );
    });

    request.addEventListener("error", () =>
      reject(new ApiError("The upload failed. Check your connection and try again.", { status: 0 })),
    );
    request.addEventListener("abort", () =>
      reject(new ApiError("The upload was cancelled.", { status: 0, code: "aborted" })),
    );

    request.send(form);
  });

  return { promise, abort: () => request.abort() };
}
