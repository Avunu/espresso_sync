// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { EvalClient } from "../../../public/js/editor/evalWorker.ts";

let client: EvalClient | undefined;

/**
 * The page's one expression engine: JSONata in a Web Worker, whose script
 * Frappe's esbuild builds from public/js/jsonata-worker.bundle.js. Started on
 * first use, so a screen that evaluates nothing never loads it.
 */
export function getEvalClient(): EvalClient {
	client ??= new EvalClient(
		() => new Worker(window.portal_boot?.jsonata_worker_url ?? "", { name: "jsonata" }),
	);
	return client;
}
