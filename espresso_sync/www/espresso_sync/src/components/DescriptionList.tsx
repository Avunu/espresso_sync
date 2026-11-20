// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ReactNode } from "react";

interface DescriptionListProps {
	/** What the facts are of, for a screen reader: "Last sync". */
	label: string;
	items: [label: string, value: ReactNode][];
}

/** A record's facts, each a label over its value, wrapping into as many columns as fit. */
export function DescriptionList({ label, items }: DescriptionListProps) {
	return (
		<dl className="es-description-list" aria-label={label}>
			{items.map(([term, value]) => (
				<div key={term}>
					<dt>{term}</dt>
					<dd>{value}</dd>
				</div>
			))}
		</dl>
	);
}
