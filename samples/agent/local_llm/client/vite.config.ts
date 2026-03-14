import { config } from "dotenv";
import { UserConfig } from "vite";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

export default async () => {
  config();

  return {
    server: {
      proxy: {
        "/api": "http://localhost:8000",
      },
    },
    build: {
      rollupOptions: {
        input: {
          main: resolve(__dirname, "index.html"),
        },
      },
      target: "esnext",
    },
    resolve: {
      dedupe: ["lit"],
    },
  } satisfies UserConfig;
};
