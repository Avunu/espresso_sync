// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useEffect } from "react";

const MESSAGE = "Leave the page? Its unsaved changes will be lost.";

/**
 * While `dirty`, asks before the page is left with unsaved changes: the browser's own
 * prompt for a reload or another site, and a confirm for a link to another of the
 * page's views, which changes only the hash, and beforeunload doesn't see that.
 * `message` is the confirm's question.
 */
export function useUnsavedGuard(dirty: boolean, message: string = MESSAGE): void {
	useEffect(() => {
		if (!dirty) return undefined;
		const warn = (event: BeforeUnloadEvent) => event.preventDefault();
		const leave = (event: MouseEvent) => {
			const link = event.target instanceof Element ? event.target.closest('a[href^="#/"]') : null;
			if (link && !window.confirm(message)) event.preventDefault();
		};
		window.addEventListener("beforeunload", warn);
		document.addEventListener("click", leave, true);
		return () => {
			window.removeEventListener("beforeunload", warn);
			document.removeEventListener("click", leave, true);
		};
	}, [dirty, message]);
}
