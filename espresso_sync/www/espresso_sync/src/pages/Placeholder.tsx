// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ReactNode } from "react";
import { Breadcrumb, BreadcrumbItem, Button, Tile } from "@carbon/react";
import { ArrowLeft } from "@carbon/react/icons";

interface PlaceholderProps {
	/** What the page is, above the name: "API spec", "Transform". */
	kind: string;
	name: string;
	children: ReactNode;
}

/** A screen whose tools aren't built yet: where it is, what it will do, and the way back. */
export function Placeholder({ kind, name, children }: PlaceholderProps) {
	return (
		<div className="es-page">
			<Breadcrumb noTrailingSlash>
				<BreadcrumbItem href="#/">Espresso Sync</BreadcrumbItem>
				<BreadcrumbItem isCurrentPage>{kind}</BreadcrumbItem>
			</Breadcrumb>
			<header className="es-heading">
				<p className="es-heading__kind">{kind}</p>
				<h1>{name}</h1>
			</header>
			<Tile className="es-placeholder">{children}</Tile>
			<div>
				<Button kind="tertiary" size="md" href="#/" renderIcon={ArrowLeft}>
					Back to the overview
				</Button>
			</div>
		</div>
	);
}
