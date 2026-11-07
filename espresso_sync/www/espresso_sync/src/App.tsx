// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect } from "react";
import type { Route } from "../../../public/js/editor/routes.ts";
import { NotFound } from "./pages/NotFound";
import { Overview } from "./pages/Overview";
import { SpecPage } from "./pages/SpecPage";
import { TransformPage } from "./pages/TransformPage";
import { PortalHeader } from "./portal/PortalHeader";
import { useRoute } from "./useRoute";

function titleOf(route: Route): string {
	switch (route.page) {
		case "home":
			return "Espresso Sync";
		case "spec":
			return `${route.name} · API spec · Espresso Sync`;
		case "transform":
			return `${route.name} · Transform · Espresso Sync`;
		case "not-found":
			return "Not found · Espresso Sync";
	}
}

function Page({ route }: { route: Route }) {
	switch (route.page) {
		case "home":
			return <Overview />;
		case "spec":
			return <SpecPage name={route.name} />;
		case "transform":
			return <TransformPage name={route.name} />;
		case "not-found":
			return <NotFound />;
	}
}

export function App() {
	const route = useRoute();
	const title = titleOf(route);

	useEffect(() => {
		document.title = title;
	}, [title]);

	return (
		<>
			<PortalHeader />
			<main id="main-content" className="es-main">
				<Page route={route} />
			</main>
		</>
	);
}
