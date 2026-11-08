// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect, useRef } from "react";
import { Content } from "@carbon/react";
import { Overview } from "./pages/Overview";
import { Spec } from "./pages/Spec";
import { Specs } from "./pages/Specs";
import { Transform } from "./pages/Transform";
import { PortalHeader } from "./portal/PortalHeader";
import { useRoute } from "./route";

const MAIN = "main-content";

/**
 * Espresso Sync's page: the Connections, the API specs, and the transforms
 * built on them. Everything it shows comes through Frappe's REST
 * API and the app's whitelisted methods, which check permissions themselves.
 */
export function App() {
	const route = useRoute();
	// A new page puts the keyboard at its start: what had the focus (the button that
	// led there, a dialog) is gone. The page as first loaded keeps the browser's focus.
	const page = `${route.section}/${route.name ?? ""}`;
	const shown = useRef(page);
	useEffect(() => {
		if (shown.current === page) return;
		shown.current = page;
		document.getElementById(MAIN)?.focus();
	}, [page]);
	return (
		<>
			<PortalHeader name="Espresso Sync" />
			<Content id={MAIN} tabIndex={-1} style={{ outline: "none" }}>
				{route.section === "connections" && <Overview />}
				{route.section === "specs" && (route.name ? <Spec name={route.name} /> : <Specs />)}
				{route.section === "transforms" && <Transform name={route.name} />}
			</Content>
		</>
	);
}
