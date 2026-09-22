/**
 * Cloudflare Pages Function: same-origin proxy for /api/*.
 *
 * The browser only ever talks to https://codeblack-sdoc.pages.dev, so the
 * frontend no longer depends on the backend's CORS allowlist. Pages forwards
 * each request to the sdoc-backend Worker server-side, where CORS does not
 * apply.
 *
 * Plain JavaScript on purpose: this file lives outside the Vite/TypeScript
 * build and is compiled and uploaded by Wrangler as a Pages Function.
 *
 * Nothing is inspected, buffered or rewritten. Request and response bodies
 * are passed through as streams so 100 MB uploads and file downloads work,
 * and every response header — Content-Disposition, X-Total-Count and the
 * rest — reaches the browser unchanged.
 */

const FALLBACK_ORIGIN = "https://sdoc-backend.teamcodeblack9.workers.dev";

export async function onRequest({ request, env }) {
  const incoming = new URL(request.url);

  // The backend echoes/validates Origin for CORS. Server-to-server there is
  // no origin to speak of, so strip it and let the request be treated as
  // same-origin by the backend.
  const headers = new Headers(request.headers);
  headers.delete("Origin");

  const init = {
    method: request.method,
    headers,
    body: request.body,
    // Pass 3xx through rather than following it, so the proxy stays faithful.
    redirect: "manual",
  };
  // Required when streaming a request body instead of buffering it.
  if (request.body) init.duplex = "half";

  if (env.BACKEND) {
    return env.BACKEND.fetch(new Request(incoming.toString(), init));
  }

  const target = new URL(incoming.pathname + incoming.search, FALLBACK_ORIGIN);
  return fetch(new Request(target.toString(), init));
}
