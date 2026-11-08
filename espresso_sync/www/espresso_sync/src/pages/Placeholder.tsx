// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ReactNode } from "react";
import { Breadcrumb, BreadcrumbItem, Stack, Tile } from "@carbon/react";
import { hrefFor } from "../route";

interface PlaceholderProps {
	/** What the page is: "API spec", "Transform". */
	kind: string;
	name: string | undefined;
	children: ReactNode;
}

/** A screen whose tools aren't built yet: where it is, what it will do, and the way back. */
export function Placeholder({ kind, name, children }: PlaceholderProps) {
	return (
		<Stack gap={6}>
			<Breadcrumb noTrailingSlash>
				<BreadcrumbItem href={hrefFor("connections")}>Connections</BreadcrumbItem>
				<BreadcrumbItem isCurrentPage>{kind}</BreadcrumbItem>
			</Breadcrumb>
			<h1>{name ?? kind}</h1>
			<Tile>{children}</Tile>
		</Stack>
	);
}
