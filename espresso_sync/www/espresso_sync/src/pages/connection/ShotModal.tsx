// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type ReactNode, type RefObject, useCallback, useEffect, useRef, useState } from "react";
import {
	Checkbox,
	ComboBox,
	FormGroup,
	InlineNotification,
	Link,
	Modal,
	Stack,
	TextInput,
} from "@carbon/react";
import { useFrappeGetCall, useFrappePostCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { optionsFor, type ShotDraft, shotErrors } from "../../../../../public/js/portal/connectionForm.ts";
import {
	type Direction,
	METHODS,
	type Shot,
	type ShotInput,
	type ShotOption,
	type ShotsAnswer,
} from "../../data/api";
import { useSession } from "../../portal/session";
import { getErrorMessage, readFailure } from "../../portal/useBackendCall";
import { hrefFor } from "../../route";
import { useSessionRead } from "../../useSessionRead";

/** What a floating menu in a modal is, besides Carbon's own list: a combo box's options. */
export const FLOATING_MENUS = [".cds--list-box__menu"];

export interface InlineCall<T> {
	/** The method's answer, or undefined when it failed: `error` then says why. */
	call: (params: Record<string, unknown>) => Promise<T | undefined>;
	busy: boolean;
	/** Why the last call failed, in the server's words. */
	error: string | null;
	/** Forget the failure: the dialog opens again without it. */
	reset: () => void;
}

/**
 * A POST whose failure is shown where it was asked for (a modal) and not as a toast, as
 * useBackendCall shows it. The rest is the same: the session timer restarts on an
 * answer, and a 403 reloads the page.
 */
export function useInlineCall<T>(method: string, fallback: string): InlineCall<T> {
	const { call: post } = useFrappePostCall<FrappeResponse<T>>(method);
	const { recordActivity, reportForbidden } = useSession();
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const call = useCallback(
		async (params: Record<string, unknown>): Promise<T | undefined> => {
			setBusy(true);
			setError(null);
			try {
				const { message } = await post(params);
				recordActivity();
				if (message === undefined) setError(fallback);
				return message;
			} catch (failure) {
				if (readFailure(failure).httpStatus === 403) reportForbidden();
				else setError(getErrorMessage(failure, fallback));
				return undefined;
			} finally {
				setBusy(false);
			}
		},
		[post, fallback, recordActivity, reportForbidden],
	);
	const reset = useCallback(() => setError(null), []);

	return { call, busy, error, reset };
}

/** One transform in a combo box. A Draft is listed, but can't be chosen. */
interface TransformItem {
	name: string;
	label: string;
	disabled: boolean;
}

/** The transforms a field offers: those of the DocType and direction, and the one it
 * holds when that is none of them (it was deleted, or is of another Connection). */
function transformItems(
	options: ShotOption[],
	dt: string,
	direction: Direction,
	current: string,
): TransformItem[] {
	const items = optionsFor(options, dt, direction).map((option) => ({
		name: option.name,
		label: option.status === "Active" ? option.name : `${option.name} (Draft)`,
		disabled: option.status !== "Active",
	}));
	if (current && !items.some((item) => item.name === current)) {
		items.push({ name: current, label: `${current} (not available)`, disabled: true });
	}
	return items;
}

function hasText({ item, inputValue }: { item: string; inputValue: string | null }): boolean {
	return !inputValue || item.toLowerCase().includes(inputValue.toLowerCase());
}

function hasLabel({ item, inputValue }: { item: TransformItem; inputValue: string | null }): boolean {
	return hasText({ item: item.label, inputValue });
}

function draftOfShot(shot: Shot | undefined): ShotDraft {
	return {
		dt: shot?.dt ?? "",
		do_import: shot?.do_import ?? 0,
		import_transform: shot?.import_transform ?? "",
		do_export: shot?.do_export ?? 0,
		export_transform: shot?.export_transform ?? "",
		update_transform: shot?.update_transform ?? "",
		follow_up_transform: shot?.follow_up_transform ?? "",
	};
}

function inputOf(draft: ShotDraft): ShotInput {
	return {
		dt: draft.dt,
		do_import: draft.do_import,
		import_transform: draft.import_transform || null,
		do_export: draft.do_export,
		export_transform: draft.export_transform || null,
		update_transform: draft.update_transform || null,
		follow_up_transform: draft.follow_up_transform || null,
	};
}

type TransformField = "import_transform" | "export_transform" | "update_transform" | "follow_up_transform";

interface TransformPickerProps {
	id: string;
	label: string;
	helper: ReactNode;
	items: TransformItem[];
	value: string;
	disabled: boolean;
	error: string | undefined;
	onChange: (name: string) => void;
}

function TransformPicker({
	id,
	label,
	helper,
	items,
	value,
	disabled,
	error,
	onChange,
}: TransformPickerProps) {
	return (
		<ComboBox
			id={id}
			titleText={label}
			placeholder="Search the transforms"
			helperText={helper}
			items={items}
			itemToString={(item) => item?.label ?? ""}
			selectedItem={items.find((item) => item.name === value) ?? null}
			shouldFilterItem={hasLabel}
			disabled={disabled}
			invalid={Boolean(error)}
			invalidText={error}
			onChange={({ selectedItem }) => onChange(selectedItem?.name ?? "")}
		/>
	);
}

export interface ShotModalProps {
	open: boolean;
	/** The Connection's name. */
	connection: string;
	/** The shot to change; none to add one. */
	shot: Shot | undefined;
	/** The DocTypes the Connection has a shot for: it takes one shot each. */
	taken: string[];
	/** `shot_options`: the transforms on the Connection's API Specs. */
	options: ShotOption[];
	/** Why the transforms couldn't be loaded. */
	optionsError: unknown;
	launcherButtonRef: RefObject<HTMLElement | null>;
	onClose: () => void;
	onSaved: (answer: ShotsAnswer) => void;
}

/**
 * Adding a shot, or changing one: whether its DocType is imported and exported, and
 * with which transforms. It is saved through `save_shot`, which holds the sync lock and
 * runs the Connection's validation; what that refuses is shown here.
 */
export function ShotModal({
	open,
	connection,
	shot,
	taken,
	options,
	optionsError,
	launcherButtonRef,
	onClose,
	onSaved,
}: ShotModalProps) {
	const [draft, setDraft] = useState(() => draftOfShot(shot));
	// the fields say what they lack once a save was tried
	const [tried, setTried] = useState(false);
	const doctypes = useFrappeGetCall<FrappeResponse<string[]>>(
		METHODS.listDoctypes,
		undefined,
		open && !shot ? undefined : null,
	);
	useSessionRead(doctypes.data, doctypes.error);
	const save = useInlineCall<ShotsAnswer>(METHODS.saveShot, "Try again.");
	// read by onRequestClose: Carbon's Escape handler keeps the one given when the modal opened
	const running = useRef(false);
	useEffect(() => {
		running.current = save.busy;
	}, [save.busy]);
	// the Save button had the focus, and is disabled while it runs: the keyboard goes on
	// from the reason it failed
	const failureRef = useRef<HTMLDivElement>(null);
	useEffect(() => {
		if (save.error) failureRef.current?.focus();
	}, [save.error]);

	const errors = tried ? shotErrors(draft) : {};
	const { dt } = draft;
	const imports = transformItems(options, dt, "Import", draft.import_transform);
	const exportsOf = (field: TransformField) => transformItems(options, dt, "Export", draft[field]);
	const choosable = (doctypes.data?.message ?? []).filter((doctype) => !taken.includes(doctype));

	function set(changes: Partial<ShotDraft>) {
		setDraft((current) => ({ ...current, ...changes }));
	}

	function submit() {
		if (running.current) return;
		setTried(true);
		if (Object.keys(shotErrors(draft)).length > 0) return;
		running.current = true;
		void save
			.call({ connection, shot: inputOf(draft), ...(shot ? { name: shot.name } : {}) })
			.then((answer) => {
				if (answer) onSaved(answer);
			});
	}

	/** What a transform field says under it: where transforms come from when it has none to offer. */
	function helperFor(items: TransformItem[], direction: Direction, otherwise: string): ReactNode {
		if (!dt) return "Choose the DocType first.";
		if (items.some((item) => !item.disabled)) return otherwise;
		return (
			<>
				No Active {direction === "Import" ? "import" : "export"} transform maps {dt} on this connection. Make
				one from an operation of an <Link href={hrefFor("specs")}>API spec</Link>.
			</>
		);
	}

	const exportItems = exportsOf("export_transform");

	return (
		<Modal
			open={open}
			size="md"
			modalHeading={shot ? `Edit the ${shot.dt} shot` : "Add shot"}
			modalLabel={connection}
			primaryButtonText={shot ? "Save" : "Add"}
			secondaryButtonText="Cancel"
			loadingStatus={save.busy ? "active" : "inactive"}
			loadingDescription="Saving"
			launcherButtonRef={launcherButtonRef}
			preventCloseOnClickOutside
			selectorsFloatingMenus={FLOATING_MENUS}
			selectorPrimaryFocus={shot ? "#shot-do-import" : "#shot-doctype"}
			// Carbon disables Cancel while it runs, but not the close button or Escape
			onRequestClose={() => {
				if (!running.current) onClose();
			}}
			onRequestSubmit={submit}
		>
			<Stack gap={7}>
				{shot ? (
					<TextInput
						id="shot-doctype"
						labelText="DocType"
						helperText="A shot keeps its DocType. Remove it and add another to change it."
						value={shot.dt}
						readOnly
					/>
				) : (
					<ComboBox
						id="shot-doctype"
						titleText="DocType"
						placeholder="Search the DocTypes"
						helperText="The DocTypes you can read that the connection has no shot for yet, but child tables and Singles."
						items={choosable}
						selectedItem={dt || null}
						shouldFilterItem={hasText}
						invalid={Boolean(doctypes.error || errors.dt)}
						invalidText={
							doctypes.error ? getErrorMessage(doctypes.error, "The DocTypes couldn't be loaded.") : errors.dt
						}
						onChange={({ selectedItem }) =>
							// a transform maps one DocType: none of those chosen fits another
							set({
								dt: selectedItem ?? "",
								import_transform: "",
								export_transform: "",
								update_transform: "",
								follow_up_transform: "",
							})
						}
					/>
				)}
				{Boolean(optionsError) && (
					<InlineNotification
						kind="error"
						lowContrast
						hideCloseButton
						title="The transforms couldn't be loaded."
						subtitle={getErrorMessage(optionsError, "Close this and try again.")}
					/>
				)}
				<FormGroup legendText="Import">
					<Stack gap={5}>
						<Checkbox
							id="shot-do-import"
							labelText="Import: read the API's objects into documents"
							checked={draft.do_import === 1}
							onChange={(_event, { checked }) => set({ do_import: checked ? 1 : 0 })}
						/>
						<TransformPicker
							id="shot-import-transform"
							label="Import transform"
							helper={helperFor(imports, "Import", "An Active import transform of this DocType.")}
							items={imports}
							value={draft.import_transform}
							disabled={!dt}
							error={errors.import_transform}
							onChange={(name) => set({ import_transform: name })}
						/>
					</Stack>
				</FormGroup>
				<FormGroup legendText="Export">
					<Stack gap={5}>
						<Checkbox
							id="shot-do-export"
							labelText="Export: send changed documents to the API"
							checked={draft.do_export === 1}
							onChange={(_event, { checked }) => set({ do_export: checked ? 1 : 0 })}
						/>
						<TransformPicker
							id="shot-export-transform"
							label="Create transform"
							helper={helperFor(
								exportItems,
								"Export",
								"Sends the documents the API does not have yet, and the others too when there is no update transform.",
							)}
							items={exportItems}
							value={draft.export_transform}
							disabled={!dt}
							error={errors.export_transform}
							onChange={(name) => set({ export_transform: name })}
						/>
						<TransformPicker
							id="shot-update-transform"
							label="Update transform (optional)"
							helper="Sends the documents the API already has, when it updates with another operation than it creates."
							items={exportsOf("update_transform")}
							value={draft.update_transform}
							disabled={!dt}
							error={errors.update_transform}
							onChange={(name) => set({ update_transform: name })}
						/>
						<TransformPicker
							id="shot-follow-up-transform"
							label="Follow-up transform (optional)"
							helper="Sent for each document right after its create or update succeeded."
							items={exportsOf("follow_up_transform")}
							value={draft.follow_up_transform}
							disabled={!dt}
							error={errors.follow_up_transform}
							onChange={(name) => set({ follow_up_transform: name })}
						/>
					</Stack>
				</FormGroup>
				{dt && !draft.do_import && !draft.do_export && <p>Only adds the Sync tab to {dt}.</p>}
				{save.error && (
					<div ref={failureRef} tabIndex={-1}>
						<InlineNotification
							kind="error"
							lowContrast
							hideCloseButton
							title="The shot couldn't be saved."
							subtitle={save.error}
							style={{ whiteSpace: "pre-line" }}
						/>
					</div>
				)}
			</Stack>
		</Modal>
	);
}
