import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const config = [
  {
    ignores: ["frontend/.next/**", "frontend/next-env.d.ts"],
  },
  ...nextVitals,
  ...nextTs,
  {
    settings: {
      next: {
        rootDir: "frontend/",
      },
    },
  },
];

export default config;
