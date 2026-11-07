// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { EvalClient } from "../../../public/js/editor/evalWorker.ts";

let client: EvalClient | undefined;

/**
 * The page's one expression engine: JSONata in a Web Worker, which Vite
 * bundles as a file of its own. Started on first use, so a screen that
 * evaluates nothing never loads it.
 */
export function getEvalClient(): EvalClient {
	client ??= new EvalClient(
		() => new Worker(new URL("./evalWorker.worker.ts", import.meta.url), { type: "module", name: "jsonata" }),
	);
	return client;
}
