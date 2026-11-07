// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Placeholder } from "./Placeholder";

/** `#/transforms/<name>`: one transform, in the editor. */
export function TransformPage({ name }: { name: string }) {
	return (
		<Placeholder kind="Transform" name={name}>
			<h2>The transform editor is on its way</h2>
			<p>
				This page will map the fields of an API operation to a DocType&apos;s, and back, with a JSONata
				expression for each field, checked against both schemas and previewed on sample data as you type.
			</p>
		</Placeholder>
	);
}
