// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { createContext, type PropsWithChildren, useCallback, useContext, useState } from "react";
import { ToastNotification } from "@carbon/react";
import type { ShowToast, ToastState } from "./types";

let nextToastId = 1;

const ToastContext = createContext<ShowToast>(() => {});

export function useToasts(): ShowToast {
	return useContext(ToastContext);
}

export function ToastProvider({ children }: PropsWithChildren) {
	const [toasts, setToasts] = useState<ToastState[]>([]);

	const showToast = useCallback<ShowToast>((next) => {
		// Newest on top; older toasts stay until they time out or are closed
		// so a burst of them can't silently replace each other.
		setToasts((current) => [{ ...next, id: nextToastId++ }, ...current]);
	}, []);

	const dismissToast = useCallback((id: number) => {
		setToasts((current) => current.filter((toast) => toast.id !== id));
	}, []);

	return (
		<ToastContext.Provider value={showToast}>
			{children}
			{/* Top-right, just under Carbon's 3rem fixed Header. */}
			<div className="es-toasts" aria-live="polite">
				{toasts.map((toast) => (
					<ToastNotification
						key={toast.id}
						kind={toast.kind}
						title={toast.title}
						{...(toast.subtitle === undefined ? {} : { subtitle: toast.subtitle })}
						timeout={toast.kind === "error" ? 0 : 8000}
						onClose={() => dismissToast(toast.id)}
						className="es-toast"
					/>
				))}
			</div>
		</ToastContext.Provider>
	);
}
