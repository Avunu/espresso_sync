// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type RefObject, useEffect, useRef, useState } from "react";
import { Dropdown, InlineNotification, Modal, Stack, TextInput } from "@carbon/react";
import { type Link, METHODS } from "../../data/api";
import { FLOATING_MENUS, useInlineCall } from "./ShotModal";

export interface LinkModalProps {
	open: boolean;
	/** The Connection's name. */
	connection: string;
	/** The DocTypes of its shots: those a document can be linked of. */
	shotDoctypes: string[];
	/** The link whose External ID to change; none to link a document. */
	link: Link | undefined;
	launcherButtonRef: RefObject<HTMLElement | null>;
	onClose: () => void;
	onSaved: (link: Link) => void;
}

/**
 * Linking a document to the object it is in the Connection's API, or changing the
 * External ID of a link. Either writes the link alone (`add_link`, `update_link`): the
 * document is not saved, so it is not sent out for it. What the server refuses (no
 * such document, an External ID that is taken) is shown here.
 */
export function LinkModal({
	open,
	connection,
	shotDoctypes,
	link,
	launcherButtonRef,
	onClose,
	onSaved,
}: LinkModalProps) {
	const [doctype, setDoctype] = useState(shotDoctypes.length === 1 ? (shotDoctypes[0] ?? "") : "");
	const [docname, setDocname] = useState("");
	const [externalId, setExternalId] = useState(link?.external_id ?? "");
	// the fields say what they lack once a save was tried
	const [tried, setTried] = useState(false);
	const add = useInlineCall<Link>(METHODS.addLink, "Try again.");
	const update = useInlineCall<Link>(METHODS.updateLink, "Try again.");
	const busy = add.busy || update.busy;
	const error = add.error ?? update.error;
	// read by onRequestClose: Carbon's Escape handler keeps the one given when the modal opened
	const running = useRef(false);
	useEffect(() => {
		running.current = busy;
	}, [busy]);
	// the Save button had the focus, and is disabled while it runs: the keyboard goes on
	// from the reason it failed
	const failureRef = useRef<HTMLDivElement>(null);
	useEffect(() => {
		if (error) failureRef.current?.focus();
	}, [error]);

	// a document that does not sync needs no External ID (`update_link`)
	const idNeeded = !link?.dont_sync;
	const missing = {
		doctype: tried && !link && !doctype,
		docname: tried && !link && !docname.trim(),
		externalId: tried && idNeeded && !externalId.trim(),
	};

	function submit() {
		if (running.current) return;
		setTried(true);
		if (idNeeded && !externalId.trim()) return;
		if (!link && (!doctype || !docname.trim())) return;
		running.current = true;
		const saved = link
			? update.call({ name: link.name, external_id: externalId.trim() })
			: add.call({ connection, doctype, docname: docname.trim(), external_id: externalId.trim() });
		void saved.then((answer) => {
			if (answer) onSaved(answer);
		});
	}

	return (
		<Modal
			open={open}
			size="sm"
			modalHeading={link ? "Edit external ID" : "Link a document"}
			modalLabel={link ? `${link.parenttype} ${link.parent}` : connection}
			primaryButtonText={link ? "Save" : "Link"}
			secondaryButtonText="Cancel"
			loadingStatus={busy ? "active" : "inactive"}
			loadingDescription="Saving"
			launcherButtonRef={launcherButtonRef}
			preventCloseOnClickOutside
			selectorsFloatingMenus={FLOATING_MENUS}
			selectorPrimaryFocus={link ? "#link-external-id" : "#link-doctype"}
			// Carbon disables Cancel while it runs, but not the close button or Escape
			onRequestClose={() => {
				if (!running.current) onClose();
			}}
			onRequestSubmit={submit}
		>
			<Stack gap={6}>
				{!link && (
					<>
						<p>
							For a document that is already in the API: the next sync updates the two, where it would
							otherwise create one of them again.
						</p>
						<Dropdown
							id="link-doctype"
							titleText="DocType"
							label="Choose a DocType"
							helperText="The DocTypes of the connection's shots."
							items={shotDoctypes}
							selectedItem={doctype || null}
							invalid={missing.doctype}
							invalidText="Choose a DocType."
							onChange={({ selectedItem }) => setDoctype(selectedItem ?? "")}
						/>
						<TextInput
							id="link-docname"
							labelText="Document"
							helperText="The document's name (its ID in the desk), exactly."
							value={docname}
							autoComplete="off"
							spellCheck={false}
							invalid={missing.docname}
							invalidText="Give the document's name."
							onChange={(event) => setDocname(event.target.value)}
						/>
					</>
				)}
				<TextInput
					id="link-external-id"
					labelText="External ID"
					helperText={
						idNeeded
							? "What the API calls the object: an import finds the document by it."
							: "The document does not sync, so this can be left empty."
					}
					value={externalId}
					autoComplete="off"
					spellCheck={false}
					invalid={missing.externalId}
					invalidText="Give the External ID."
					onChange={(event) => setExternalId(event.target.value)}
				/>
				{link && (
					<p>
						Only the link changes: the document is not saved, and nothing is sent to the API. The next sync
						takes the object with this ID as the document's.
					</p>
				)}
				{error && (
					<div ref={failureRef} tabIndex={-1}>
						<InlineNotification
							kind="error"
							lowContrast
							hideCloseButton
							title={link ? "The external ID couldn't be saved." : "The document couldn't be linked."}
							subtitle={error}
							style={{ whiteSpace: "pre-line" }}
						/>
					</div>
				)}
			</Stack>
		</Modal>
	);
}
