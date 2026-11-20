// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type RefObject, useState } from "react";
import { RadioButton, RadioButtonGroup, Stack } from "@carbon/react";
import { plural } from "../../../../../public/js/portal/datetime.ts";
import type { LogFilters } from "../../../../../public/js/portal/logs.ts";
import { ConfirmDangerModal } from "../../components/ConfirmDangerModal";
import { type ClearLogsAnswer, type ClearLogsFilters, METHODS } from "../../data/api";
import { useToasts } from "../../portal/Toasts";
import { useInlineCall } from "../connection/ShotModal";

/** Which entries to delete: those the table's filters match, a Connection's, or all. */
type Scope = "filters" | "connection" | "all";

export interface ClearLogsModalProps {
	open: boolean;
	/** The filters the table shows by, the fixed ones included. */
	filters: LogFilters;
	/** Whether every Connection's entries may be cleared from here: not on a Connection's own page. */
	allowAll: boolean;
	/** What opened the dialog, which gets the focus back. */
	launcherButtonRef?: RefObject<HTMLElement | null> | undefined;
	onClose: () => void;
	/** After entries were deleted: the table reads the log again. */
	onCleared: () => void;
}

/** The filters as `clear_logs` takes them, or null when it cannot filter by one that is
 * set: it knows no period's start, no document, no error code, and not the entries of
 * documents from those of requests. */
function clearFilters(filters: LogFilters): ClearLogsFilters | null {
	if (filters.since || filters.doc || filters.docs || filters.code) return null;
	const found: ClearLogsFilters = {};
	if (filters.status === "Success" || filters.status === "Failure") found.sync_status = filters.status;
	else if (filters.status) return null;
	if (filters.direction === "Import" || filters.direction === "Export") {
		found.sync_direction = filters.direction;
	} else if (filters.direction) return null;
	if (filters.doctype) found.sync_doctype = filters.doctype;
	if (filters.transform) found.transform = filters.transform;
	return found;
}

/**
 * Deleting log entries, which can't be undone: those the current filters match, all of one
 * Connection's, or every entry there is (typed out to confirm). Only the log goes: the
 * synced documents and their links to the API stay.
 */
export function ClearLogsModal({
	open,
	filters,
	allowAll,
	launcherButtonRef,
	onClose,
	onCleared,
}: ClearLogsModalProps) {
	// a failure is said in the dialog: a toast would be behind it, out of the keyboard's reach
	const {
		call,
		busy: loading,
		error,
		reset,
	} = useInlineCall<ClearLogsAnswer>(METHODS.clearLogs, "The entries couldn't be deleted.");
	const showToast = useToasts();
	const connection = filters.connection;
	const narrowed = clearFilters(filters);
	// "the current filters" means something only when one besides the Connection is set
	const byFilters = narrowed !== null && Object.keys(narrowed).length > 0;
	const unusable = narrowed === null;

	const fallback: Scope = byFilters ? "filters" : connection ? "connection" : "all";
	const [chosen, setChosen] = useState<Scope | null>(null);
	// each opening starts from the narrowest scope there is
	const [wasOpen, setWasOpen] = useState(open);
	if (wasOpen !== open) {
		setWasOpen(open);
		setChosen(null);
		reset();
	}
	const available =
		chosen === "filters" ? byFilters : chosen === "connection" ? Boolean(connection) : chosen === "all";
	const scope = chosen && available ? chosen : fallback;
	const nothing = scope === "all" && !allowAll;

	async function clear() {
		const params: Record<string, unknown> = {};
		if (scope === "all") {
			params["confirm"] = "all";
		} else {
			if (connection) params["connection"] = connection;
			if (scope === "filters" && narrowed) params["filters"] = narrowed;
		}
		const result = await call(params);
		if (!result) return;
		const { deleted } = result;
		showToast({
			kind: "success",
			title: deleted
				? `${plural(deleted, "log entry", "log entries")} deleted.`
				: "There were no entries to delete.",
		});
		onCleared();
		onClose();
	}

	return (
		<ConfirmDangerModal
			open={open}
			heading="Clear log entries?"
			label="Sync log"
			primaryText="Delete entries"
			confirmText={scope === "all" && allowAll ? "all" : undefined}
			busy={loading}
			error={error}
			disabled={nothing}
			launcherButtonRef={launcherButtonRef}
			onConfirm={() => void clear()}
			onClose={onClose}
		>
			<Stack gap={6}>
				<p>
					Deleted entries can't be brought back. The synced documents and their links to the API stay as they
					are.
				</p>
				<RadioButtonGroup
					legendText="Entries to delete"
					name="clear-logs-scope"
					orientation="vertical"
					valueSelected={scope}
					{...(unusable
						? {
								helperText:
									"The entries can't be deleted by period, document or error code, or without those of requests: only by status, direction, DocType and transform.",
							}
						: {})}
					onChange={(value) => {
						if (value === "filters" || value === "connection" || value === "all") setChosen(value);
					}}
				>
					<RadioButton
						id="clear-logs-filters"
						value="filters"
						labelText={
							connection
								? `The entries of ${connection} that match the current filters`
								: "The entries that match the current filters"
						}
						disabled={!byFilters}
					/>
					<RadioButton
						id="clear-logs-connection"
						value="connection"
						labelText={connection ? `All entries of ${connection}` : "All entries of one connection"}
						disabled={!connection}
					/>
					{allowAll && (
						<RadioButton id="clear-logs-all" value="all" labelText="All entries of every connection" />
					)}
				</RadioButtonGroup>
				{nothing && <p>Choose a connection or a filter first.</p>}
			</Stack>
		</ConfirmDangerModal>
	);
}
