// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ReactNode } from "react";
import {
	StructuredListBody,
	StructuredListCell,
	StructuredListRow,
	StructuredListWrapper,
} from "@carbon/react";

/** A record's fields, a label and a value to a row. */
export function Details({ label, fields }: { label: string; fields: [string, ReactNode][] }) {
	return (
		<StructuredListWrapper isCondensed aria-label={label}>
			<StructuredListBody>
				{fields.map(([name, value]) => (
					<StructuredListRow key={name}>
						<StructuredListCell noWrap>{name}</StructuredListCell>
						<StructuredListCell>{value}</StructuredListCell>
					</StructuredListRow>
				))}
			</StructuredListBody>
		</StructuredListWrapper>
	);
}
