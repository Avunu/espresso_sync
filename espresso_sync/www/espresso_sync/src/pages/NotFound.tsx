// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Button } from "@carbon/react";
import { ArrowLeft } from "@carbon/react/icons";

/** Any hash that names no screen. */
export function NotFound() {
	return (
		<div className="es-page">
			<header className="es-heading">
				<h1>Nothing here</h1>
				<p>This address doesn&apos;t point to anything in Espresso Sync.</p>
			</header>
			<div>
				<Button kind="tertiary" size="md" href="#/" renderIcon={ArrowLeft}>
					Back to the overview
				</Button>
			</div>
		</div>
	);
}
