// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { Theme } from "@carbon/react";
import { FrappeProvider } from "frappe-react-sdk";
import { SessionProvider } from "./session";
import { ToastProvider } from "./Toasts";

/** Renders the page's React app into index.html's `#app`, inside the providers it shares. */
export function mountPortal(app: ReactNode): void {
	const container = document.getElementById("app");
	if (!container) return;

	createRoot(container).render(
		<FrappeProvider
			{...(window.sitename === undefined ? {} : { siteName: window.sitename })}
			// frappe-js-sdk defaults X-Frappe-Site-Name to window.location.hostname,
			// which is "localhost" when a dev bench is browsed at localhost:<port> - every
			// SDK request then 404s (site not found). customHeaders merge last, so this wins.
			customHeaders={{ "X-Frappe-Site-Name": window.sitename ?? "" }}
			// Nothing on the page listens for realtime events.
			enableSocket={false}
		>
			<Theme theme="g10">
				<SessionProvider>
					<ToastProvider>{app}</ToastProvider>
				</SessionProvider>
			</Theme>
		</FrappeProvider>,
	);
}
