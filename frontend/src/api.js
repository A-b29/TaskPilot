// Tiny fetch wrapper: adds the login token, turns API errors into readable messages.
const BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const SESSION_KEY = "taskpilot.session";

export function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY));
  } catch {
    return null;
  }
}

export function saveSession(session) {
  try {
    session ? localStorage.setItem(SESSION_KEY, JSON.stringify(session)) : localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage blocked: session lasts until reload */
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => (onUnauthorized = fn);

export async function api(path, { method = "GET", body } = {}) {
  const token = loadSession()?.token;
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: {
        ...(body && { "Content-Type": "application/json" }),
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      body: body && JSON.stringify(body),
    });
  } catch {
    // fetch only throws on network failure, a CORS rejection, or a blocked http:// call from an https:// page
    if (BASE.includes("localhost") && !location.hostname.includes("localhost"))
      throw new Error("This site isn't connected to the backend: VITE_API_URL was not set when it was built.");
    throw new Error(`Can't reach the server (${BASE}). If the app was idle, the free backend may be waking up, so try again in about a minute.`);
  }
  const data = await res.json().catch(() => null);
  if (res.status === 401 && token) onUnauthorized();
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(
      Array.isArray(detail)
        ? detail.map((e) => `${e.loc?.at(-1)}: ${e.msg}`).join(". ")
        : detail || `Something went wrong (error ${res.status}). Please try again.`
    );
  }
  return data;
}

export const localToday = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD in the user's timezone
