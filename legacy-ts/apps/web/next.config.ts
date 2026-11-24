import type { NextConfig } from "next";

const config: NextConfig = {
  // core ships TypeScript source, so Next must compile it.
  transpilePackages: ["@scraper/core"],
};

export default config;
