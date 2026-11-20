// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type FormEvent, useEffect, useRef, useState } from "react";
import {
	Button,
	ButtonSet,
	Callout,
	Form,
	FormGroup,
	InlineNotification,
	Link,
	NumberInput,
	PasswordInput,
	RadioButton,
	RadioButtonGroup,
	Select,
	SelectItem,
	Stack,
	TextInput,
	Tile,
} from "@carbon/react";
import { Launch, TrashCan } from "@carbon/react/icons";
import { useFrappeGetCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import {
	type ConnectionDraft,
	connectionErrors,
	connectionPayload,
	draftOf,
	hostOf,
	type SecretChange,
} from "../../../../../public/js/portal/connectionForm.ts";
import { formatAbsolute } from "../../../../../public/js/portal/datetime.ts";
import { BusyButton } from "../../components/BusyButton";
import { ConfirmDangerModal } from "../../components/ConfirmDangerModal";
import {
	authHintsOf,
	CONNECTION,
	type ConnectionDetail,
	type CronPreview,
	METHODS,
	type StatusRow,
} from "../../data/api";
import { useToasts } from "../../portal/Toasts";
import { useUnsavedGuard } from "../../portal/useUnsavedGuard";
import { deskFormUrl } from "../../route";
import { useSessionRead } from "../../useSessionRead";
import { useInlineCall } from "./ShotModal";

interface SettingsTabProps {
	/** The Connection as `get_connection` answered: what the form's fields are saved as. */
	connection: ConnectionDetail;
	/** Its `list_status` row: nothing is saved while it is queued or running. */
	status: StatusRow | undefined;
	/** Called after a save, for the page to read the Connection again; the form waits for it. */
	onSaved: () => Promise<unknown>;
	/** Told whenever the form gets or loses unsaved changes. */
	onDirtyChange: (dirty: boolean) => void;
	/** Delete connection was pressed, on `launcher`. */
	onDelete: (launcher: HTMLElement) => void;
}

/** The Sync Frequency options of the DocType, and how each reads. */
const FREQUENCIES: [value: string, text: string][] = [
	["Manual", "Manual: only with Sync now"],
	["Every Minute", "Every minute"],
	["Hourly", "Hourly"],
	["Daily", "Daily"],
	["Weekly", "Weekly"],
	["Monthly", "Monthly"],
	["Cron", "Cron: by a rule"],
];

const FIELDS: (keyof ConnectionDraft)[] = [
	"server_url",
	"allowed_host",
	"auth_type",
	"api_key",
	"sync_frequency",
	"cron_rule",
	"api_rate_limit",
];

const MONOSPACE = { fontFamily: "var(--cds-code-02-font-family, monospace)" } as const;

/**
 * `#/connections/<name>/settings`: where the API is, how to authenticate, and when to
 * sync. The form is a draft over what is saved. The secret is write-only: its field
 * starts empty every time, an empty one keeps what is stored, and only "Remove stored
 * secret" takes it away. Enabled and the shots are not here: each saves by itself.
 */
export function SettingsTab({ connection, status, onSaved, onDirtyChange, onDelete }: SettingsTabProps) {
	const { name } = connection;
	const saved = draftOf(connection);
	// only what was changed is kept: an untouched field follows what is saved
	const [edits, setEdits] = useState<Partial<ConnectionDraft>>({});
	const [secret, setSecret] = useState("");
	// a field's error shows once the field was left, or Save was tried
	const [checked, setChecked] = useState<ReadonlySet<keyof ConnectionDraft>>(new Set());
	const [removing, setRemoving] = useState(false);
	const removeLauncher = useRef<HTMLButtonElement>(null);
	const failureRef = useRef<HTMLDivElement>(null);
	const showToast = useToasts();
	// Through save_connection, which answers as get_connection does. The REST API answers a
	// save with the document, where the secret is a mask as long as it is.
	const save = useInlineCall<ConnectionDetail>(METHODS.saveConnection, "Try again.");
	const removal = useInlineCall<ConnectionDetail>(METHODS.saveConnection, "Try again.");

	const draft: ConnectionDraft = { ...saved, ...edits };
	const dirty = secret !== "" || FIELDS.some((field) => draft[field] !== saved[field]);
	const errors = connectionErrors(draft);
	const syncing = status !== undefined && status.state !== "idle";
	const basic = draft.auth_type === "Basic";
	const isCron = draft.sync_frequency === "Cron";

	useUnsavedGuard(dirty);
	useEffect(() => {
		onDirtyChange(dirty);
	}, [dirty, onDirtyChange]);
	// the tab is left: its changes went with it
	useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

	// Save had the focus, and shows as busy while it runs: the keyboard goes on from the
	// reason it failed
	useEffect(() => {
		if (save.error) failureRef.current?.focus();
	}, [save.error]);

	// the rule the next times are asked for: the saved one, then each one the field is left with
	const [previewRule, setPreviewRule] = useState(saved.cron_rule.trim());
	const preview = useFrappeGetCall<FrappeResponse<CronPreview>>(
		METHODS.cronPreview,
		{ cron_rule: previewRule },
		isCron && previewRule ? undefined : null,
	);
	useSessionRead(preview.data, preview.error);
	const previewed = previewRule === draft.cron_rule.trim() ? preview.data?.message : undefined;

	function change(field: keyof ConnectionDraft, value: string) {
		setEdits((current) => ({ ...current, [field]: value }));
	}

	function leave(field: keyof ConnectionDraft) {
		setChecked((current) => new Set(current).add(field));
	}

	function errorOf(field: keyof ConnectionDraft): string | undefined {
		return checked.has(field) ? errors[field] : undefined;
	}

	function discard() {
		setEdits({});
		setSecret("");
		setChecked(new Set());
		save.reset();
	}

	function submit(event: FormEvent) {
		event.preventDefault();
		if (!dirty || syncing || save.busy) return;
		setChecked(new Set(FIELDS));
		const invalid = FIELDS.find((field) => errors[field]);
		if (invalid) {
			document.getElementById(`connection-${invalid.replaceAll("_", "-")}`)?.focus();
			return;
		}
		const secretChange: SecretChange = secret ? { kind: "set", value: secret } : { kind: "keep" };
		const { modified, ...values } = connectionPayload(draft, secretChange, connection.modified);
		// a failure is shown above the buttons, from the hook's error
		void save.call({ connection: name, values, modified }).then(async (answer) => {
			if (!answer) return;
			showToast({ kind: "success", title: `${name} was saved.` });
			await onSaved();
			discard();
		});
	}

	function removeSecret() {
		// what is saved, not the draft: taking the secret away saves nothing else
		const { modified, ...values } = connectionPayload(saved, { kind: "remove" }, connection.modified);
		// a failure is shown in the dialog, from the hook's error
		void removal.call({ connection: name, values, modified }).then(async (answer) => {
			if (!answer) return;
			showToast({ kind: "success", title: `The stored secret of ${name} was removed.` });
			await onSaved();
			setRemoving(false);
		});
	}

	const hints = authHintsOf(connection);
	const hinted =
		hints?.auth_type &&
		(hints.auth_type !== draft.auth_type || (hints.api_key !== null && hints.api_key !== draft.api_key))
			? hints
			: null;

	const urlError = errorOf("server_url");
	const hostError = errorOf("allowed_host");
	const cronError =
		errorOf("cron_rule") ?? (previewed?.valid === false ? "This is not a cron rule." : undefined);
	const limitError = errorOf("api_rate_limit");
	const urlHost = hostOf(draft.server_url);

	return (
		<Stack gap={9} style={{ maxInlineSize: "40rem" }}>
			<Form aria-label="Settings" noValidate onSubmit={submit}>
				<Stack gap={7}>
					<TextInput
						id="connection-name"
						labelText="Name"
						readOnly
						value={name}
						helperText={
							<>
								API specs carry the name, so it is changed in the desk.{" "}
								<Link href={deskFormUrl(CONNECTION, name)} renderIcon={Launch} size="sm">
									Rename in the desk
								</Link>
							</>
						}
					/>

					<FormGroup legendText={<span className="es-form-legend">Server</span>}>
						<Stack gap={6}>
							<TextInput
								id="connection-server-url"
								type="url"
								labelText="Server URL"
								helperText="The base URL of the API: each transform's path is added to it."
								autoComplete="off"
								spellCheck={false}
								invalid={Boolean(urlError)}
								invalidText={urlError}
								value={draft.server_url}
								onChange={(event) => change("server_url", event.target.value)}
								onBlur={() => leave("server_url")}
							/>
							<TextInput
								id="connection-allowed-host"
								labelText="Allowed host (optional)"
								helperText={
									urlHost
										? `Credentials are sent to this host only. Empty is the Server URL's own, ${urlHost}.`
										: "Credentials are sent to this host only. Empty is the Server URL's own."
								}
								autoComplete="off"
								spellCheck={false}
								invalid={Boolean(hostError)}
								invalidText={hostError}
								value={draft.allowed_host}
								onChange={(event) => change("allowed_host", event.target.value)}
								onBlur={() => leave("allowed_host")}
							/>
						</Stack>
					</FormGroup>

					<FormGroup legendText={<span className="es-form-legend">Authentication</span>}>
						<Stack gap={6}>
							{hinted && (
								<Callout
									kind="info"
									lowContrast
									title="The API spec suggests another authentication."
									subtitle={
										`${hinted.spec}: ${hinted.auth_type}` +
										(hinted.api_key ? `, with the header ${hinted.api_key}.` : ".") +
										(hinted.note ? ` ${hinted.note}` : "")
									}
									actionButtonLabel="Use the spec's suggestion"
									onActionButtonClick={() => {
										setEdits((current) => ({
											...current,
											auth_type: hinted.auth_type ?? draft.auth_type,
											...(hinted.api_key === null ? {} : { api_key: hinted.api_key }),
										}));
									}}
									style={{ maxInlineSize: "none" }}
								/>
							)}
							<RadioButtonGroup
								legendText="Type"
								name="connection-auth-type"
								orientation="vertical"
								valueSelected={draft.auth_type}
								onChange={(value) => change("auth_type", value === "Basic" ? "Basic" : "Header-based")}
							>
								<RadioButton
									id="connection-auth-type"
									value="Header-based"
									labelText="Header-based: a header carries a key or a token"
								/>
								<RadioButton
									id="connection-auth-type-basic"
									value="Basic"
									labelText="Basic: a username and a password"
								/>
							</RadioButtonGroup>
							<TextInput
								id="connection-api-key"
								labelText={basic ? "Username" : "Header name"}
								{...(basic ? {} : { placeholder: "Authorization" })}
								autoComplete="off"
								spellCheck={false}
								value={draft.api_key}
								onChange={(event) => change("api_key", event.target.value)}
							/>
							<div>
								<PasswordInput
									id="connection-api-secret"
									labelText={basic ? "Password" : "Header value"}
									{...(connection.has_secret ? { placeholder: "Unchanged" } : {})}
									helperText={
										connection.has_secret
											? "A secret is stored. Leave empty to keep it."
											: "No secret is stored."
									}
									autoComplete="new-password"
									value={secret}
									onChange={(event) => setSecret(event.target.value)}
								/>
								{connection.has_secret && (
									<Button
										ref={removeLauncher}
										kind="danger--ghost"
										size="sm"
										disabled={syncing}
										style={{ marginBlockStart: "var(--cds-spacing-03)" }}
										onClick={() => {
											removal.reset();
											setRemoving(true);
										}}
									>
										Remove stored secret
									</Button>
								)}
							</div>
						</Stack>
					</FormGroup>

					<FormGroup legendText={<span className="es-form-legend">Schedule</span>}>
						<Stack gap={6}>
							<Select
								id="connection-sync-frequency"
								labelText="Frequency"
								helperText="The scheduler syncs an enabled connection this often."
								value={draft.sync_frequency}
								onChange={(event) => change("sync_frequency", event.target.value)}
							>
								{FREQUENCIES.map(([value, text]) => (
									<SelectItem key={value} value={value} text={text} />
								))}
							</Select>
							{isCron && (
								<TextInput
									id="connection-cron-rule"
									labelText="Cron rule"
									placeholder="0 6 * * *"
									helperText={
										previewed?.valid && previewed.next.length > 0
											? `Next: ${previewed.next.map(formatAbsolute).join(", ")}.`
											: "Minute, hour, day of the month, month and day of the week."
									}
									autoComplete="off"
									spellCheck={false}
									style={MONOSPACE}
									invalid={Boolean(cronError)}
									invalidText={cronError}
									value={draft.cron_rule}
									onChange={(event) => change("cron_rule", event.target.value)}
									onBlur={() => {
										leave("cron_rule");
										setPreviewRule(draft.cron_rule.trim());
									}}
								/>
							)}
							<NumberInput
								id="connection-api-rate-limit"
								label="Requests per minute (optional)"
								helperText="The most requests a sync sends in a minute. Empty or 0 is no limit."
								allowEmpty
								min={0}
								step={1}
								invalid={Boolean(limitError)}
								invalidText={limitError}
								value={draft.api_rate_limit}
								onChange={(_event, { value }) => change("api_rate_limit", String(value))}
								onBlur={() => leave("api_rate_limit")}
							/>
						</Stack>
					</FormGroup>

					{syncing && (
						<InlineNotification
							kind="info"
							lowContrast
							hideCloseButton
							title={`${name} is syncing.`}
							subtitle="Its settings can be saved when it is done."
						/>
					)}
					{save.error && (
						<div ref={failureRef} tabIndex={-1}>
							<InlineNotification
								kind="error"
								lowContrast
								hideCloseButton
								title="The settings couldn't be saved."
								subtitle={save.error}
							/>
						</div>
					)}
					<ButtonSet>
						<Button kind="secondary" disabled={!dirty || save.busy} onClick={discard}>
							Discard
						</Button>
						<BusyButton
							type="submit"
							kind="primary"
							busy={save.busy}
							busyText="Saving…"
							disabled={!dirty || syncing}
						>
							Save
						</BusyButton>
					</ButtonSet>
				</Stack>
			</Form>

			<Tile>
				<Stack gap={5}>
					<h2
						style={{
							margin: 0,
							fontSize: "var(--cds-heading-compact-02-font-size)",
							fontWeight: "var(--cds-heading-compact-02-font-weight)",
							lineHeight: "var(--cds-heading-compact-02-line-height)",
						}}
					>
						Delete connection
					</h2>
					<p style={{ fontSize: "var(--cds-body-compact-01-font-size)" }}>
						Deletes {name}, its log entries and its documents' links to the API. The synced documents stay.
					</p>
					<div>
						<Button
							kind="danger--tertiary"
							renderIcon={TrashCan}
							onClick={(event) => onDelete(event.currentTarget)}
						>
							Delete connection
						</Button>
					</div>
				</Stack>
			</Tile>

			<ConfirmDangerModal
				open={removing}
				heading={`Remove the stored secret of ${name}?`}
				label="Connection"
				primaryText="Remove"
				busy={removal.busy}
				error={removal.error}
				launcherButtonRef={removeLauncher}
				onConfirm={removeSecret}
				onClose={() => setRemoving(false)}
			>
				<p>
					{name} then sends its requests without credentials, until a new secret is saved. It can't be brought
					back: nothing here can read it.
					{dirty && " The unsaved changes of the form stay as they are."}
				</p>
			</ConfirmDangerModal>
		</Stack>
	);
}
