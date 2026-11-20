// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type RefObject, useEffect, useRef, useState } from "react";
import { InlineNotification, Modal, NumberInput, NumberInputSkeleton, Stack } from "@carbon/react";
import { useFrappeGetCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { plural } from "../../../../../public/js/portal/datetime.ts";
import { METHODS, type Retention } from "../../data/api";
import { useToasts } from "../../portal/Toasts";
import { getErrorMessage } from "../../portal/useBackendCall";
import { useSessionRead } from "../../useSessionRead";
import { useInlineCall } from "../connection/ShotModal";

/** What `set_retention` takes: a whole number of days between these. */
const MIN_DAYS = 1;
const MAX_DAYS = 3650;

export interface RetentionModalProps {
	open: boolean;
	/** What opened the dialog, which gets the focus back. */
	launcherButtonRef?: RefObject<HTMLElement | null> | undefined;
	onClose: () => void;
}

/** How long the Sync log keeps an entry: the Pull Log's row in the desk's Log Settings. */
export function RetentionModal({ open, launcherButtonRef, onClose }: RetentionModalProps) {
	// asked for only once the dialog opens, and again each time it does
	const { data, error, isLoading, mutate } = useFrappeGetCall<FrappeResponse<Retention>>(
		METHODS.getRetention,
		undefined,
		open ? undefined : null,
		{ revalidateOnFocus: false },
	);
	useSessionRead(data, error);
	const stored = data?.message?.days;
	// a failure is said in the dialog: a toast would be behind it, out of the keyboard's reach
	const {
		call,
		busy: loading,
		error: failure,
		reset,
	} = useInlineCall<Retention>(METHODS.setRetention, "The retention couldn't be saved.");
	const failureRef = useRef<HTMLDivElement>(null);
	// Save had the focus, and is disabled while it runs: the keyboard goes on from the reason
	useEffect(() => {
		if (failure) failureRef.current?.focus();
	}, [failure]);
	const showToast = useToasts();
	// what is typed, until it is saved or the dialog closes
	const [typed, setTyped] = useState<number | string | null>(null);
	// read by onRequestClose: Carbon's Escape handler keeps the one given when the modal opened
	const running = useRef(loading);
	useEffect(() => {
		running.current = loading;
	}, [loading]);

	const value = typed ?? stored ?? "";
	const days = typeof value === "number" ? value : Number(value);
	const valid = value !== "" && Number.isInteger(days) && days >= MIN_DAYS && days <= MAX_DAYS;

	function close() {
		if (running.current) return;
		setTyped(null);
		reset();
		onClose();
	}

	async function save() {
		if (running.current || !valid) return;
		const result = await call({ days });
		if (!result) return;
		showToast({
			kind: "success",
			title: `Log entries are kept for ${plural(result.days, "day", "days")}.`,
		});
		void mutate();
		setTyped(null);
		onClose();
	}

	let body;
	if (error) {
		body = (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title="The retention couldn't be loaded."
				subtitle={getErrorMessage(error, "Close this and try again.")}
			/>
		);
	} else if (isLoading || stored === undefined) {
		// only while the dialog shows: a skeleton in a closed one never ends
		body = open ? <NumberInputSkeleton /> : null;
	} else {
		body = (
			<NumberInput
				id="log-retention-days"
				label="Days to keep an entry"
				helperText="Older entries are deleted once a day, with the site's other logs."
				min={MIN_DAYS}
				max={MAX_DAYS}
				step={1}
				value={value}
				invalid={!valid}
				invalidText={`A whole number of days, from ${MIN_DAYS} to ${MAX_DAYS}.`}
				disableWheel
				onChange={(_event, state) => setTyped(state.value)}
			/>
		);
	}

	return (
		<Modal
			open={open}
			size="sm"
			modalHeading="Log retention"
			modalLabel="Sync log"
			primaryButtonText="Save"
			secondaryButtonText="Cancel"
			primaryButtonDisabled={!valid || stored === undefined || days === stored}
			loadingStatus={loading ? "active" : "inactive"}
			loadingDescription="Saving"
			{...(launcherButtonRef ? { launcherButtonRef } : {})}
			onRequestClose={close}
			onRequestSubmit={() => void save()}
		>
			<Stack gap={6}>
				<p>
					The log has an entry for every request and every document of every sync. This applies to all
					connections.
				</p>
				{body}
				{failure && (
					<div ref={failureRef} tabIndex={-1}>
						<InlineNotification
							kind="error"
							lowContrast
							hideCloseButton
							title="The retention couldn't be saved."
							subtitle={failure}
						/>
					</div>
				)}
			</Stack>
		</Modal>
	);
}
