// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useCallback, useMemo, useState } from "react";
import { useToasts } from "../portal/Toasts";
import { type BackendResult, useBackendCall } from "../portal/useBackendCall";
import { METHODS, type StatusRow } from "./api";

type Call = (params?: Record<string, unknown>) => Promise<BackendResult<StatusRow>>;

export interface SyncActions {
	/** Queue a sync of the Connection. Each answers whether it was done. */
	syncNow: (name: string) => Promise<boolean>;
	/** Forget what was synced when, and queue a sync of everything. */
	resync: (name: string) => Promise<boolean>;
	setEnabled: (name: string, enabled: boolean) => Promise<boolean>;
	/** The Connections an action is running for. */
	busy: ReadonlySet<string>;
}

/**
 * The actions on a Connection that the Overview, the list and the detail page share.
 * Each says how it went in a toast (a failure with the server's reason), and on success
 * calls `onDone`, for the caller to refetch the status.
 */
export function useSyncActions(onDone: () => void): SyncActions {
	const sync = useBackendCall<StatusRow>(METHODS.syncNow, "The sync couldn't be started.");
	const again = useBackendCall<StatusRow>(METHODS.resync, "The resync couldn't be started.");
	const enable = useBackendCall<StatusRow>(METHODS.setEnabled, "The connection couldn't be changed.");
	const showToast = useToasts();
	// how many actions run for each Connection: one that ends leaves the others' as they are
	const [running, setRunning] = useState<Readonly<Record<string, number>>>({});

	const run = useCallback(
		async (name: string, call: Call, params: Record<string, unknown>, done: string): Promise<boolean> => {
			setRunning((current) => ({ ...current, [name]: (current[name] ?? 0) + 1 }));
			const result = await call({ connection: name, ...params });
			setRunning(({ [name]: count = 1, ...others }) =>
				count > 1 ? { ...others, [name]: count - 1 } : others,
			);
			if (!result.ok) return false;
			showToast({ kind: "success", title: done });
			onDone();
			return true;
		},
		[onDone, showToast],
	);

	const syncNow = useCallback(
		(name: string) => run(name, sync.call, {}, `${name} is queued to sync.`),
		[run, sync.call],
	);
	const resync = useCallback(
		(name: string) => run(name, again.call, {}, `${name} is queued to sync everything again.`),
		[run, again.call],
	);
	const setEnabled = useCallback(
		(name: string, enabled: boolean) =>
			run(
				name,
				enable.call,
				{ enabled: enabled ? 1 : 0 },
				enabled ? `${name} is enabled.` : `${name} is paused.`,
			),
		[run, enable.call],
	);

	const busy = useMemo(() => new Set(Object.keys(running)), [running]);
	return { syncNow, resync, setEnabled, busy };
}
