// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type ReactNode, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { FrappeProvider } from "frappe-react-sdk";
import { SessionProvider } from "./session";
import { ThemeRoot } from "./theme";
import { ToastProvider } from "./Toasts";

/** Renders the app into index.html's `#app`, inside the providers every screen shares. */
export function mountPortal(app: ReactNode): void {
	const container = document.getElementById("app");
	if (!container) return;

	createRoot(container).render(
		<StrictMode>
			<FrappeProvider
				{...(window.sitename === undefined ? {} : { siteName: window.sitename })}
				// frappe-js-sdk defaults X-Frappe-Site-Name to window.location.hostname,
				// which is "localhost" when a dev bench is browsed at localhost:<port> - every
				// request would then 404 (site not found). customHeaders merge last, so this wins.
				customHeaders={{ "X-Frappe-Site-Name": window.sitename ?? "" }}
				// Nothing on the page listens for realtime events yet.
				enableSocket={false}
			>
				<ThemeRoot>
					<SessionProvider>
						<ToastProvider>{app}</ToastProvider>
					</SessionProvider>
				</ThemeRoot>
			</FrappeProvider>
		</StrictMode>,
	);
}
