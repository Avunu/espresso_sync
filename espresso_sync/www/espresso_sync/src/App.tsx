// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Content } from "@carbon/react";
import { Overview } from "./pages/Overview";
import { Spec } from "./pages/Spec";
import { Specs } from "./pages/Specs";
import { Transform } from "./pages/Transform";
import { PortalHeader } from "./portal/PortalHeader";
import { useRoute } from "./route";

/**
 * Espresso Sync's page: the Connections, the API specs, and the transforms
 * built on them. Everything it shows comes through Frappe's REST
 * API and the app's whitelisted methods, which check permissions themselves.
 */
export function App() {
	const route = useRoute();
	return (
		<>
			<PortalHeader name="Espresso Sync" />
			<Content>
				{route.section === "connections" && <Overview />}
				{route.section === "specs" && (route.name ? <Spec name={route.name} /> : <Specs />)}
				{route.section === "transforms" && <Transform name={route.name} />}
			</Content>
		</>
	);
}
