import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

// next/core-web-vitals: React, hooks and Next.js correctness rules. (next/typescript is not enabled: the codebase
// deliberately uses `any` for API payloads.)
const config = [
  { ignores: [".next/**", "node_modules/**", "playwright-report/**", "test-results/**", "next-env.d.ts"] },
  ...compat.extends("next/core-web-vitals"),
  // Apostrophes and quotes in JSX text render correctly in React; escaping all UI copy adds noise, not safety.
  { rules: { "react/no-unescaped-entities": "off" } },
];

export default config;
