/**
 * In-memory Request Deduplication and Short-TTL Query Cache for ENIGMA / EQUILIBRA Frontend.
 * 
 * Features:
 * 1. In-flight promise deduplication (prevents multiple identical simultaneous network requests).
 * 2. 10-second TTL cache for idempotent GET requests during tab switching and navigation.
 * 3. Automatic cache invalidation upon any mutating POST/PUT/DELETE request.
 */

const responseCache = new Map();
const pendingRequests = new Map();

export async function cachedFetch(url, options = {}, ttlMs = 8000) {
  const method = (options.method || 'GET').toUpperCase();

  // Any mutation immediately busts the entire query cache
  if (method !== 'GET') {
    responseCache.clear();
    return fetch(url, options);
  }

  const cacheKey = `${url}::${JSON.stringify(options.headers || {})}`;
  const now = Date.now();

  // 1. Check valid cache
  const cached = responseCache.get(cacheKey);
  if (cached && (now - cached.timestamp < ttlMs)) {
    return cached.response.clone();
  }

  // 2. Check in-flight request deduplication
  if (pendingRequests.has(cacheKey)) {
    const existingPromise = pendingRequests.get(cacheKey);
    const resp = await existingPromise;
    return resp.clone();
  }

  // 3. Dispatch fresh request with deduplication
  const fetchPromise = (async () => {
    try {
      const response = await fetch(url, options);
      if (response.ok) {
        responseCache.set(cacheKey, {
          timestamp: Date.now(),
          response: response.clone()
        });
      }
      return response;
    } finally {
      pendingRequests.delete(cacheKey);
    }
  })();

  pendingRequests.set(cacheKey, fetchPromise);
  const result = await fetchPromise;
  return result.clone();
}

export function invalidateApiCache() {
  responseCache.clear();
}
