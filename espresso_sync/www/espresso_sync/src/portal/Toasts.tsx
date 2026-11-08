// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { createContext, type PropsWithChildren, useCallback, useContext, useState } from "react";
import { ToastNotification } from "@carbon/react";
import type { ShowToast, ToastState } from "./types";

let nextToastId = 1;

/** How long a confirmation shows: as long as the desk's frappe.show_alert() shows one. */
const CONFIRMATION_MS = 7000;

const ToastContext = createContext<ShowToast>(() => {});

export function useToasts(): ShowToast {
	return useContext(ToastContext);
}

export function ToastProvider({ children }: PropsWithChildren) {
	const [toasts, setToasts] = useState<ToastState[]>([]);

	const showToast = useCallback<ShowToast>((next) => {
		// Newest nearest the corner; an older toast stays until it is closed or times
		// out, so a burst of them can't silently replace each other.
		setToasts((current) => [...current, { ...next, id: nextToastId++ }]);
	}, []);

	const dismissToast = useCallback((id: number) => {
		setToasts((current) => current.filter((toast) => toast.id !== id));
	}, []);

	return (
		<ToastContext.Provider value={showToast}>
			{children}
			{/* Bottom right, where the desk shows its own alerts. */}
			<div
				style={{
					position: "fixed",
					bottom: "1rem",
					right: "1rem",
					maxHeight: "calc(100vh - 5rem)",
					overflowY: "auto",
					zIndex: 9000,
				}}
			>
				{toasts.map((toast) => (
					<ToastNotification
						key={toast.id}
						kind={toast.kind}
						title={toast.title}
						// a confirmation goes by itself, as in the desk; a warning or an error stays
						timeout={toast.kind === "success" || toast.kind === "info" ? CONFIRMATION_MS : 0}
						onClose={() => dismissToast(toast.id)}
					/>
				))}
			</div>
		</ToastContext.Provider>
	);
}
