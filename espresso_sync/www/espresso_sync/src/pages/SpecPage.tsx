// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Placeholder } from "./Placeholder";

/** `#/specs/<name>`: one API spec. */
export function SpecPage({ name }: { name: string }) {
	return (
		<Placeholder kind="API spec" name={name}>
			<h2>Importing API specs is on its way</h2>
			<p>
				This page will import an OpenAPI document (pasted, uploaded or fetched from a URL), check it, and list
				its operations, so a transform can start from one of them.
			</p>
		</Placeholder>
	);
}
