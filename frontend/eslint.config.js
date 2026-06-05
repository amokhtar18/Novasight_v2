import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";

export default tseslint.config(
  // Ignore build output and dependencies.
  {
    ignores: ["dist/**", "node_modules/**", "coverage/**"],
  },

  // Base JS rules.
  js.configs.recommended,

  // TypeScript rules.
  ...tseslint.configs.recommended,

  // React Hooks rules.
  {
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },

  // Project-specific overrides.
  {
    rules: {
      // Allow void for intentionally fire-and-forget promises.
      "@typescript-eslint/no-floating-promises": "off",
      // Permit explicit `any` only when unavoidable (e.g. ECharts option types).
      "@typescript-eslint/no-explicit-any": "warn",
      // Avoid accidental unused imports/vars.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  }
);
