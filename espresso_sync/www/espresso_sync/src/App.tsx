// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect, useRef } from "react";
import { Content } from "@carbon/react";
import { Connection } from "./pages/Connection";
import { Connections } from "./pages/Connections";
import { Log } from "./pages/Log";
import { Logs } from "./pages/Logs";
import { Overview } from "./pages/Overview";
import { Spec } from "./pages/Spec";
import { Specs } from "./pages/Specs";
import { Transform } from "./pages/Transform";
import { Transforms } from "./pages/Transforms";
import { MAIN, PortalHeader, SECTION_LABELS } from "./portal/PortalHeader";
import { useRoute } from "./route";

const NAME = "Espresso Sync";

/**
 * Espresso Sync's page: the health of the Connections, the Connections themselves,
 * the log of what they synced, and the transforms and API specs they sync through.
 * Everything it shows comes through Frappe's REST API and the app's whitelisted
 * methods, which check permissions themselves.
 */
export function App() {
	const route = useRoute();
	// A new page puts the keyboard at its start: what had the focus (the button that
	// led there, a dialog) is gone. The page as first loaded keeps the browser's focus,
	// and so does a page whose tab or filters change: that is still the same page.
	const page = `${route.section}/${route.name ?? ""}`;
	const shown = useRef(page);
	useEffect(() => {
		if (shown.current === page) return;
		shown.current = page;
		// the browser would scroll the focused main to the window's top, under the header
		document.getElementById(MAIN)?.focus({ preventScroll: true });
		window.scrollTo(0, 0);
	}, [page]);

	// "<record> · <Section> · Espresso Sync": what a tab, a bookmark and the history show
	const section = SECTION_LABELS.find(([to]) => to === route.section)?.[1];
	const title = [route.name, section, NAME].filter(Boolean).join(" · ");
	useEffect(() => {
		document.title = title;
	}, [title]);

	return (
		<>
			<PortalHeader name={NAME} section={route.section} />
			{/* At least the window's height below the 3rem header: the light theme's background
			    is only as tall as the page, so a short page would end above a white band. */}
			<Content id={MAIN} tabIndex={-1} style={{ outline: "none", minBlockSize: "calc(100vh - 3rem)" }}>
				{route.section === "overview" && <Overview />}
				{route.section === "connections" &&
					(route.name ? (
						<Connection key={route.name} name={route.name} tab={route.tab} query={route.query} />
					) : (
						<Connections query={route.query} />
					))}
				{route.section === "logs" && (route.name ? <Log name={route.name} /> : <Logs query={route.query} />)}
				{route.section === "specs" && (route.name ? <Spec name={route.name} /> : <Specs />)}
				{route.section === "transforms" &&
					(route.name ? <Transform key={route.name} name={route.name} /> : <Transforms />)}
			</Content>
		</>
	);
}
