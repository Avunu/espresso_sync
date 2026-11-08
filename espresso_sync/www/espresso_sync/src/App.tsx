// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Content } from "@carbon/react";
import { Overview } from "./pages/Overview";
import { Placeholder } from "./pages/Placeholder";
import { PortalHeader } from "./portal/PortalHeader";
import { useRoute } from "./route";

/**
 * Espresso Sync's page: the Connections now, and the API specs and transforms
 * built on them as they land. Everything it shows comes through Frappe's REST
 * API and the app's whitelisted methods, which check permissions themselves.
 */
export function App() {
	const route = useRoute();
	return (
		<>
			<PortalHeader name="Espresso Sync" />
			<Content>
				{route.section === "connections" && <Overview />}
				{route.section === "specs" && (
					<Placeholder kind="API spec" name={route.name}>
						Importing an API&apos;s OpenAPI document, to list the operations a transform can start from, is on
						its way.
					</Placeholder>
				)}
				{route.section === "transforms" && (
					<Placeholder kind="Transform" name={route.name}>
						The transform editor, which maps an operation&apos;s fields to a DocType&apos;s and back with a
						JSONata expression for each, is on its way.
					</Placeholder>
				)}
			</Content>
		</>
	);
}
