import type { KnipConfig } from "knip";

const config: KnipConfig = {
  entry: ["src/main.tsx"],
  project: ["src/**/*.{ts,tsx}"],
  ignore: ["src/**/*.test.{ts,tsx}"],
  // Intentional public API exports from useModelCapabilities hook
  ignoreExportsUsedInFile: {
    interface: true,
    type: true,
  },
};

export default config;
