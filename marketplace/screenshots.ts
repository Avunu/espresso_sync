// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ShotSpec } from "./shots.d.ts";

// The demo from espresso_sync/demo.py: one Connection to a made-up shop API, and the
// Active transform its shot imports the shop's tasks with.
const formReady = (doctype: string, name: string) =>
	`window.cur_frm && cur_frm.doctype === ${JSON.stringify(doctype)} && cur_frm.doc.name === ${JSON.stringify(name)} && !cur_frm.is_dirty()`;

export default {
	demo: { date: "2026-01-15", seed: 1 },
	shots: [
		{
			name: "connection",
			route: "/app/espresso-sync-connection/Example%20Shop",
			alt: "An Espresso Sync Connection to a shop API, with a shot that imports its tasks as ToDos through an Active transform",
			waitForFn: formReady("Espresso Sync Connection", "Example Shop"),
			mask: [".frappe-timestamp"],
		},
		{
			name: "transform",
			route: "/app/espresso-sync-transform/Example%20Shop%20Tasks",
			alt: "An Active Espresso Sync Transform mapping the shop API's tasks to ToDos with JSONata rules",
			waitForFn: formReady("Espresso Sync Transform", "Example Shop Tasks"),
			mask: [".frappe-timestamp"],
		},
	],
} satisfies ShotSpec;
