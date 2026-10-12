const API_KEY_STORAGE_KEY = "lg:chat:apiKey";
const API_KEY_HOST_STORAGE_KEY = "lg:chat:apiKeyHost";
const API_KEY_ORIGIN_PREFIX = "lg:chat:apiKey:";

function originOf(apiUrl: string): string | null {
  try {
    return new URL(apiUrl).origin;
  } catch {
    return null;
  }
}

export function getApiKey(apiUrl: string): string | null {
  try {
    if (typeof window === "undefined") return null;
    const currentHost = originOf(apiUrl);
    if (!currentHost) return null;
    const stored = window.localStorage.getItem(
      API_KEY_ORIGIN_PREFIX + currentHost,
    );
    if (stored !== null) return stored;
    // Migrate the previous single-origin entry without sending it to another API.
    if (window.localStorage.getItem(API_KEY_HOST_STORAGE_KEY) === currentHost) {
      const legacy = window.localStorage.getItem(API_KEY_STORAGE_KEY);
      if (legacy) {
        window.localStorage.setItem(
          API_KEY_ORIGIN_PREFIX + currentHost,
          legacy,
        );
      }
      return legacy;
    }
    return null;
  } catch {
    // no-op
  }

  return null;
}

export function setApiKey(apiUrl: string, apiKey: string): void {
  const host = originOf(apiUrl);
  if (typeof window === "undefined" || !host) return;
  if (apiKey) {
    window.localStorage.setItem(API_KEY_ORIGIN_PREFIX + host, apiKey);
  } else {
    window.localStorage.removeItem(API_KEY_ORIGIN_PREFIX + host);
  }
  if (window.localStorage.getItem(API_KEY_HOST_STORAGE_KEY) === host) {
    window.localStorage.removeItem(API_KEY_STORAGE_KEY);
    window.localStorage.removeItem(API_KEY_HOST_STORAGE_KEY);
  }
}
