/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the SDOC backend, no trailing slash. The only configuration
   * this app needs, and not a secret. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
