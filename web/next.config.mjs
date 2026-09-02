/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Next writes its own CLAUDE.md/AGENTS.md at the web root otherwise, which
  // collides with the harness instructions this repo is about.
  agentRules: false,
};

export default nextConfig;
