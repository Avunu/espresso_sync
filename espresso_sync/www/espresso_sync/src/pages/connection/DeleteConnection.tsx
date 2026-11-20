// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { RefObject } from "react";
import { Link, SkeletonText, UnorderedList, ListItem } from "@carbon/react";
import { useFrappeGetCall, useFrappePostCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { plural } from "../../../../../public/js/portal/datetime.ts";
import { ConfirmDangerModal } from "../../components/ConfirmDangerModal";
import { type DeleteImpact, type Deleted, METHODS } from "../../data/api";
import { getErrorMessage } from "../../portal/useBackendCall";
import { hrefFor } from "../../route";
import { useSessionRead } from "../../useSessionRead";

// The two confirmations a Connection asks for, from its row in the list and from its
// own page: deleting it, and syncing everything again.

interface DeleteConnectionProps {
	open: boolean;
	/** The Connection's name. */
	connection: string;
	/** What opened the dialog, which gets the focus back. */
	launcherButtonRef: RefObject<HTMLElement | null>;
	onClose: () => void;
	/** Called once the Connection is gone. */
	onDeleted: () => void;
}

/**
 * Deleting a Connection: what goes with it (its log entries, its documents' links) and
 * what refuses it (its API specs, a sync that runs), asked of the server each time the
 * dialog opens. The name is typed to confirm.
 */
export function DeleteConnection({
	open,
	connection,
	launcherButtonRef,
	onClose,
	onDeleted,
}: DeleteConnectionProps) {
	const impact = useFrappeGetCall<FrappeResponse<DeleteImpact>>(
		METHODS.deleteImpact,
		{ connection },
		open ? undefined : null,
		// what it counts changes with every sync: never the answer of an earlier opening
		{ revalidateOnMount: true, dedupingInterval: 0 },
	);
	const { call, loading, error, isCompleted, reset } = useFrappePostCall<FrappeResponse<Deleted>>(
		METHODS.deleteConnection,
	);
	useSessionRead(impact.data, impact.error);
	useSessionRead(isCompleted, error);

	const found = impact.data?.message;
	const syncing = found !== undefined && found.state !== "idle";
	const hasSpecs = found !== undefined && found.specs.length > 0;

	function confirm() {
		call({ connection, confirm: connection }).then(
			() => onDeleted(),
			// shown in the dialog, from the hook's error
			() => {},
		);
	}

	let body;
	if (impact.error) {
		body = (
			<p>{getErrorMessage(impact.error, "What a delete removes couldn't be loaded. Close and try again.")}</p>
		);
	} else if (!found) {
		// only while the dialog shows: a skeleton in a closed one never ends
		body = open ? <SkeletonText paragraph lineCount={2} /> : null;
	} else if (hasSpecs) {
		body = (
			<>
				<p>
					{connection} has {plural(found.specs.length, "API spec", "API specs")}. Delete{" "}
					{found.specs.length === 1 ? "it" : "them"} first:
				</p>
				<UnorderedList style={{ marginBlockStart: "var(--cds-spacing-03)", marginInlineStart: "1rem" }}>
					{found.specs.map((spec) => (
						<ListItem key={spec}>
							<Link href={hrefFor("specs", spec)}>{spec}</Link>
						</ListItem>
					))}
				</UnorderedList>
			</>
		);
	} else if (syncing) {
		body = <p>{connection} is syncing: delete it when it is done.</p>;
	} else {
		body = (
			<p>
				Deletes {plural(found.logs, "log entry", "log entries")} and unlinks{" "}
				{plural(found.links, "document", "documents")}. Synced documents and their Sync tab stay. This can't
				be undone.
			</p>
		);
	}

	return (
		<ConfirmDangerModal
			open={open}
			heading={`Delete ${connection}?`}
			label="Connection"
			primaryText="Delete"
			confirmText={connection}
			busy={loading}
			error={error ? getErrorMessage(error, "Try again.") : null}
			disabled={!found || hasSpecs || syncing}
			launcherButtonRef={launcherButtonRef}
			onConfirm={confirm}
			onClose={() => {
				reset();
				onClose();
			}}
		>
			{body}
		</ConfirmDangerModal>
	);
}

interface ResyncConnectionProps {
	open: boolean;
	/** The Connection's name. */
	connection: string;
	/** Whether the resync is being queued. */
	busy: boolean;
	launcherButtonRef: RefObject<HTMLElement | null>;
	onConfirm: () => void;
	onClose: () => void;
}

/** Syncing everything of a Connection again: nothing is deleted, but it is a long sync
 * that sends every document, so it is asked first. */
export function ResyncConnection({
	open,
	connection,
	busy,
	launcherButtonRef,
	onConfirm,
	onClose,
}: ResyncConnectionProps) {
	return (
		<ConfirmDangerModal
			open={open}
			heading={`Resync everything of ${connection}?`}
			label="Connection"
			primaryText="Resync"
			busy={busy}
			launcherButtonRef={launcherButtonRef}
			onConfirm={onConfirm}
			onClose={onClose}
		>
			<p>
				Forgets when each shot last imported and exported, and queues a sync. That sync imports every object
				again and exports every document again, so it can take long and uses the API's rate limit. Nothing is
				deleted.
			</p>
		</ConfirmDangerModal>
	);
}
