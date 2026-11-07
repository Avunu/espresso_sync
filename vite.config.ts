// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * Builds the /espresso_sync page (espresso_sync/www/espresso_sync): a React app
 * whose entry is src/main.tsx, into espresso_sync/public/dist/.
 *
 * The entry and its stylesheet are named `espresso-sync.bundle.<hash>.js` and
 * `.css`, the shape `scripts/vite-register.mjs` (and frappe-nix's build
 * preload) register in the bench's assets.json as `espresso-sync.bundle.js` and
 * `.css`; index.html asks for them by those names. Shared chunks, the
 * expression engine's worker and the fonts are loaded by the bundle itself,
 * relative to `base`, so they need no names of their own.
 *
 * The source is not named `*.bundle.*` and is not under public/: Frappe's own
 * esbuild would otherwise build it a second time, without this config.
 */

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [react()],
	base: "/assets/espresso_sync/dist/",
	publicDir: false,
	css: {
		// Carbon's Sass still uses syntax newer Sass deprecates; that is Carbon's to change.
		preprocessorOptions: { scss: { quietDeps: true } },
	},
	build: {
		target: "es2022",
		outDir: "espresso_sync/public/dist",
		// Frappe's esbuild writes here too; old hashes are its build's to clean.
		emptyOutDir: false,
		manifest: ".vite/manifest.espresso-sync.json",
		chunkSizeWarningLimit: 1500,
		rolldownOptions: {
			input: { "espresso-sync": "espresso_sync/www/espresso_sync/src/main.tsx" },
			output: {
				entryFileNames: "js/[name].bundle.[hash].js",
				chunkFileNames: "js/espresso-sync-[name]-[hash].js",
				assetFileNames: (asset) =>
					asset.names.some((name) => name.endsWith(".css"))
						? "css/[name].bundle.[hash][extname]"
						: "assets/espresso-sync/[name]-[hash][extname]",
			},
		},
	},
	worker: {
		format: "es",
		rolldownOptions: {
			output: { entryFileNames: "js/espresso-sync-[name]-[hash].js" },
		},
	},
});
