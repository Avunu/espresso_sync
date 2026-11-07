// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type PropsWithChildren, useEffect, useSyncExternalStore } from "react";
import { Theme } from "@carbon/react";

const DARK = "(prefers-color-scheme: dark)";

function subscribe(onChange: () => void): () => void {
	const query = window.matchMedia(DARK);
	query.addEventListener("change", onChange);
	return () => query.removeEventListener("change", onChange);
}

/** Whether the system asks for a dark theme, following it as it changes. */
export function usePrefersDark(): boolean {
	return useSyncExternalStore(subscribe, () => window.matchMedia(DARK).matches);
}

/**
 * Carbon's g10 theme, or g100 when the system is dark. The theme's tokens
 * (`--cds-*`) apply inside this element, which fills the page; the document's
 * own color-scheme follows, for its scrollbars and form controls.
 */
export function ThemeRoot({ children }: PropsWithChildren) {
	const dark = usePrefersDark();
	useEffect(() => {
		document.documentElement.style.colorScheme = dark ? "dark" : "light";
	}, [dark]);
	return (
		<Theme theme={dark ? "g100" : "g10"} className="es-root">
			{children}
		</Theme>
	);
}
