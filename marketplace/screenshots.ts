// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ShotSpec } from "./shots.d.ts";

// The demo from espresso_sync/demo.py: one Connection to a made-up shop API, the shop's
// OpenAPI description, and the Active transform that imports its tasks as ToDos.
const formReady = (doctype: string, name: string) =>
	`window.cur_frm && cur_frm.doctype === ${JSON.stringify(doctype)} && cur_frm.doc.name === ${JSON.stringify(name)} && !cur_frm.is_dirty()`;

// The /espresso_sync page has drawn its data: no Carbon skeleton is left on it. The page has
// one (light) theme, so its shots are taken in that theme alone.
const NO_SKELETON = "!document.querySelector('.cds--skeleton, .cds--skeleton__text')";

export default {
	demo: { date: "2026-01-15", seed: 1 },
	shots: [
		{
			name: "editor",
			route: "/espresso_sync#/transforms/Example%20Shop%20Tasks",
			alt: "The transform editor: the shop API's task fields mapped to a ToDo's with JSONata rules, each previewed on the sample tasks",
			// the rules have been evaluated on the sample in the browser
			waitForFn: `${NO_SKELETON} && !!document.querySelector('#transform-editor[aria-busy="false"]') && document.querySelectorAll('[role=treeitem]').length > 5`,
			// open the ToDo status rule: its expression, what it reads and its value on each sample item;
			// the click scrolls the field into view, so scroll back up to the title and actions
			actions: [
				{ click: '[id="target:/status"]' },
				{ waitFor: '#transform-editor[aria-busy="false"]' },
				{ scroll: { y: 0 } },
			],
			// tall enough for the title, the actions and the rule's values on the sample
			viewport: { width: 1440, height: 1080, deviceScaleFactor: 2 },
			themes: ["light"],
			readme: "hero",
			featured: true,
		},
		{
			name: "spec",
			route: "/espresso_sync#/specs/Example%20Shop%20-%20Shop",
			alt: "The shop API's OpenAPI operations, imported as an API Spec, each with a button that starts a transform on it",
			waitForFn: `${NO_SKELETON} && document.querySelectorAll('table[aria-label="Operations"] tbody tr').length === 5`,
			// tall enough for the spec's details and the whole operations table
			viewport: { width: 1440, height: 1080, deviceScaleFactor: 2 },
			themes: ["light"],
			readme: "feature",
			featured: true,
		},
		{
			name: "connection",
			route: "/desk/espresso-sync-connection/Example%20Shop",
			alt: "An Espresso Sync Connection to the shop API, with a shot that imports its tasks as ToDos through the Active transform",
			waitForFn: formReady("Espresso Sync Connection", "Example Shop"),
			mask: [".frappe-timestamp"],
			readme: "feature",
		},
	],
} satisfies ShotSpec;
