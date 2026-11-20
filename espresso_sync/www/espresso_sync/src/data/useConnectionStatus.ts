// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useCallback } from "react";
import { useFrappeGetCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { useSessionRead } from "../useSessionRead";
import { METHODS, type StatusList, type StatusRow } from "./api";

/** While a Connection is queued or syncing, its status is asked for this often. */
const ACTIVE_MS = 5000;
/** And otherwise this often: a scheduled sync starts by itself. */
const IDLE_MS = 30_000;

const NO_ROWS: StatusRow[] = [];

function refreshInterval(latest: FrappeResponse<StatusList> | undefined): number {
	const active = latest?.message?.connections.some((row) => row.state !== "idle");
	return active ? ACTIVE_MS : IDLE_MS;
}

export interface ConnectionStatus {
	/** The Connections, or the one asked for (none when there is no such Connection). */
	rows: StatusRow[];
	/** The server's time when it answered: what `deriveHealth` and `relativeTime` take. */
	now: string | undefined;
	error: unknown;
	isLoading: boolean;
	/** Ask again now: after an action that changes a Connection's state. */
	mutate: () => Promise<unknown>;
}

/**
 * The status of every Connection, or of `connection` alone, kept current by polling:
 * there are no realtime events. Nothing is asked while the tab is hidden.
 */
export function useConnectionStatus(connection?: string): ConnectionStatus {
	const { data, error, isLoading, mutate } = useFrappeGetCall<FrappeResponse<StatusList>>(
		METHODS.listStatus,
		connection ? { connection } : undefined,
		undefined,
		{ refreshInterval, refreshWhenHidden: false },
	);
	useSessionRead(data, error);
	const refetch = useCallback(() => mutate(), [mutate]);
	return {
		rows: data?.message?.connections ?? NO_ROWS,
		now: data?.message?.now,
		error,
		isLoading,
		mutate: refetch,
	};
}
