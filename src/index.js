/**
 * Cloudflare Worker entrypoint / proxy for the SDOC FastAPI backend
 * container (see PROJECT_RULES.md §2, §16 — deployment target: Cloudflare
 * Containers).
 *
 * This Worker does no business logic of its own: it only forwards every
 * request to the one running backend container instance. All
 * classification/extraction/comparison/reliability logic stays exactly
 * where PROJECT_RULES.md §8 puts it (backend/pipeline/*), unchanged.
 *
 * Single fixed instance, not load-balanced: the FastAPI app tracks
 * batch-upload progress (POST /api/emails/upload with an organizer-bundle
 * zip) in an in-process ThreadPoolExecutor (backend/main.py _run_batch()).
 * That state lives inside one running container process, so every request
 * — including GET /api/batches/{batch_id} polling — must land on the SAME
 * instance. Routing by a fixed name (not per-path, not random) guarantees
 * that.
 */
import { Container } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

const INSTANCE_NAME = "sdoc-backend-primary";

export class BackendContainer extends Container {
  // Matches backend/Dockerfile's EXPOSE 8080 / PORT=8080 default.
  defaultPort = 8080;

  // Comfortably larger than the observed ~11.5-minute full 520-email batch
  // run (see PROJECT_RULES.md §20), so the container is never put to sleep
  // mid-batch. The batch runs as an in-process FastAPI BackgroundTask
  // *after* the triggering upload request has already returned a response,
  // so no new request arrives to "renew" container activity during that
  // window — the frontend is deliberately NOT relied on to poll just to
  // keep the container awake (see task constraints). 30 minutes gives
  // roughly 2.5x headroom over the local baseline, to absorb slower
  // network I/O to Supabase/the AI provider from a cloud environment.
  // Re-measure after a real Cloudflare batch run and raise this further if
  // it is ever observed to be too tight.
  sleepAfter = "30m";

  // Forwarded into the container process's environment. Every name here
  // must be set as a Worker secret before deploying (`wrangler secret put
  // <NAME>`) — never hardcoded here or in wrangler.jsonc. See
  // backend/config.py for the canonical Settings() field list and
  // .env.example for local development.
  envVars = {
    APP_ENV: env.APP_ENV,
    SUPABASE_URL: env.SUPABASE_URL,
    SUPABASE_KEY: env.SUPABASE_KEY,
    GEMINI_API_KEY: env.GEMINI_API_KEY,
    OPENCODE_API_KEY: env.OPENCODE_API_KEY,
    OPENCODE_MODEL: env.OPENCODE_MODEL,
    FRONTEND_URL: env.FRONTEND_URL,
  };
}

export default {
  async fetch(request, env) {
    const id = env.BACKEND_CONTAINER.idFromName(INSTANCE_NAME);
    const container = env.BACKEND_CONTAINER.get(id);
    return container.fetch(request);
  },
};
