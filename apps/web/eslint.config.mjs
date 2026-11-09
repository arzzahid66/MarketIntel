// eslint-config-next 16 ships a native flat config, so no FlatCompat wrapper.
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  ...coreWebVitals,
  ...typescript,
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts"],
  },
  {
    rules: {
      // Tokens are httpOnly cookies read on the server; a stray client-side
      // storage write would silently break that model.
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: "Session state lives in httpOnly cookies." },
      ],
    },
  },
];

export default config;
