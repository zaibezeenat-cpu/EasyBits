import nextConfig from "eslint-config-next";
import coreWebVitalsConfig from "eslint-config-next/core-web-vitals";
import typescriptConfig from "eslint-config-next/typescript";

const config = [
  ...nextConfig,
  ...coreWebVitalsConfig,
  ...typescriptConfig,
  {
    rules: {
      "react/no-unescaped-entities": "off",
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
];

export default config;
