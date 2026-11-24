// Fail fast at server start (not at build) if the environment is invalid.
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { loadEnv } = await import("@scraper/core");
    loadEnv();
  }
}
