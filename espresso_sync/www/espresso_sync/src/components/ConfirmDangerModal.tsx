// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type ReactNode, type RefObject, useEffect, useId, useRef, useState } from "react";
import { InlineNotification, Modal, Stack, TextInput } from "@carbon/react";

interface ConfirmDangerModalProps {
	open: boolean;
	/** The question: "Delete Shop?" */
	heading: string;
	/** Above the heading: what the question is about. */
	label?: string | undefined;
	/** The red button: "Delete". */
	primaryText: string;
	/** Text the user must type before the red button works: a name, "all". */
	confirmText?: string | undefined;
	/** Whether the action is running. */
	busy: boolean;
	/** Why the action failed, shown in the dialog and given the focus. */
	error?: string | null | undefined;
	/** A reason the action can't be taken at all: the red button stays disabled. */
	disabled?: boolean;
	/** What opened the dialog, which gets the focus back. */
	launcherButtonRef?: RefObject<HTMLElement | null> | undefined;
	onConfirm: () => void;
	onClose: () => void;
	/** What the action does, and what it leaves alone. */
	children: ReactNode;
}

/**
 * The confirmation of an action that can't be undone. It opens with the focus on
 * Cancel, so Enter backs out, and it stays open while the action runs and when it
 * fails. With `confirmText`, the action waits until that text is typed.
 */
export function ConfirmDangerModal({
	open,
	heading,
	label,
	primaryText,
	confirmText,
	busy,
	error,
	disabled = false,
	launcherButtonRef,
	onConfirm,
	onClose,
	children,
}: ConfirmDangerModalProps) {
	const inputId = useId();
	const [typed, setTyped] = useState("");
	// each opening starts with nothing typed
	const [wasOpen, setWasOpen] = useState(open);
	if (wasOpen !== open) {
		setWasOpen(open);
		setTyped("");
	}
	// read by onRequestClose: Carbon's Escape handler keeps the one given when the modal opened
	const running = useRef(busy);
	useEffect(() => {
		running.current = busy;
	}, [busy]);
	// the red button had the focus, and is disabled while it runs: the keyboard goes on
	// from the reason it failed
	const failureRef = useRef<HTMLDivElement>(null);
	useEffect(() => {
		if (error) failureRef.current?.focus();
	}, [error]);

	const confirmed = confirmText === undefined || typed.trim() === confirmText;

	return (
		<Modal
			open={open}
			danger
			size="sm"
			modalHeading={heading}
			{...(label ? { modalLabel: label } : {})}
			primaryButtonText={primaryText}
			secondaryButtonText="Cancel"
			primaryButtonDisabled={disabled || !confirmed}
			loadingStatus={busy ? "active" : "inactive"}
			loadingDescription="Working"
			{...(launcherButtonRef ? { launcherButtonRef } : {})}
			preventCloseOnClickOutside
			selectorPrimaryFocus=".cds--modal-footer .cds--btn--secondary"
			// Carbon disables Cancel while it runs, but not the close button or Escape
			onRequestClose={() => {
				if (!running.current) onClose();
			}}
			onRequestSubmit={() => {
				if (!running.current && !disabled && confirmed) onConfirm();
			}}
		>
			<Stack gap={6}>
				<div>{children}</div>
				{confirmText !== undefined && (
					<TextInput
						id={inputId}
						labelText={`Type ${confirmText} to confirm`}
						value={typed}
						autoComplete="off"
						spellCheck={false}
						onChange={(event) => setTyped(event.target.value)}
					/>
				)}
				{error && (
					<div ref={failureRef} tabIndex={-1}>
						<InlineNotification
							kind="error"
							lowContrast
							hideCloseButton
							title="It couldn't be done."
							subtitle={error}
						/>
					</div>
				)}
			</Stack>
		</Modal>
	);
}
