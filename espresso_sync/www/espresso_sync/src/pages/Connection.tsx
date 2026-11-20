// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type CSSProperties, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import {
	ActionableNotification,
	Button,
	Callout,
	InlineNotification,
	MenuButton,
	MenuItem,
	MenuItemDivider,
	SkeletonText,
	Stack,
	Tab,
	TabList,
	TabPanel,
	TabPanels,
	Tabs,
	Tooltip,
} from "@carbon/react";
import { ConnectionSignal, Renew } from "@carbon/react/icons";
import { useFrappeGetCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { describeSchedule, parseServerDatetime } from "../../../../public/js/portal/datetime.ts";
import { deriveHealth } from "../../../../public/js/portal/health.ts";
import { BusyButton } from "../components/BusyButton";
import { EnabledToggle } from "../components/EnabledToggle";
import { PageHeader } from "../components/PageHeader";
import { StatusIndicator } from "../components/StatusIndicator";
import { CONNECTION, type ConnectionDetail, METHODS, type StatusRow } from "../data/api";
import { useConnectionStatus } from "../data/useConnectionStatus";
import { useSyncActions } from "../data/useSyncActions";
import { useToasts } from "../portal/Toasts";
import { getErrorMessage, readFailure } from "../portal/useBackendCall";
import { type ConnectionTab, deskFormUrl, hrefFor, navigate } from "../route";
import { useSessionRead } from "../useSessionRead";
import { ActivityTab } from "./connection/ActivityTab";
import { CheckConnection, useConnectionCheck } from "./connection/CheckConnection";
import { DeleteConnection, ResyncConnection } from "./connection/DeleteConnection";
import { LinksTab } from "./connection/LinksTab";
import { SettingsTab } from "./connection/SettingsTab";
import { ShotsTab } from "./connection/ShotsTab";

export interface ConnectionProps {
	name: string;
	/** The tab of `#/connections/<name>/<tab>`; undefined is the Activity tab. */
	tab: ConnectionTab | undefined;
	/** The route's query: the Linked documents tab's filters. */
	query: Readonly<Record<string, string>>;
}

/** The tabs in their order; the first has no segment of its own in the route. */
const TABS: (ConnectionTab | undefined)[] = [undefined, "shots", "links", "settings"];

/** The role of a notice that says what is wrong and asks nothing: Carbon's own is a dialog's. */
const NEWS = "status";

/** A tab's content, in line with the header and the notices above it. */
const PANEL: CSSProperties = { paddingInline: 0 };

const DIRTY = "Save or discard the settings first: the test uses what is saved.";

/** Rule 5 of the health: an attempt that never set Last Pull, which only a sync that
 * finished does. Its reason is in the Error Log, not in the Connection's own log. */
function didNotFinish(row: StatusRow): boolean {
	if (row.state !== "idle" || !row.enabled || row.problems.length > 0 || !row.last_sync_attempt) return false;
	const attempt = parseServerDatetime(row.last_sync_attempt);
	const pull = row.last_pull ? parseServerDatetime(row.last_pull) : null;
	return attempt !== null && (pull === null || pull < attempt);
}

/** Space follows a tab as Enter does: the tabs are links, which only Enter presses. */
function pressOnSpace(event: KeyboardEvent) {
	if (event.key !== " " || !(event.currentTarget instanceof HTMLElement)) return;
	event.preventDefault();
	event.currentTarget.click();
}

/**
 * `#/connections/<name>`: one Connection, its activity, shots, linked documents and
 * settings. It is read through `get_connection`, never as the document itself, so
 * nothing of its secret reaches the page: only whether one is stored.
 */
export function Connection({ name, tab, query }: ConnectionProps) {
	const { data, error, mutate } = useFrappeGetCall<FrappeResponse<ConnectionDetail>>(METHODS.getConnection, {
		connection: name,
	});
	useSessionRead(data, error);
	const status = useConnectionStatus(name);
	const detail = data?.message;
	const [row] = status.rows;
	const { mutate: mutateStatus } = status;

	const refresh = useCallback(() => Promise.all([mutate(), mutateStatus()]), [mutate, mutateStatus]);
	const refreshed = useCallback(() => void refresh(), [refresh]);
	const actions = useSyncActions(refreshed);
	const check = useConnectionCheck(name);
	const showToast = useToasts();

	// A sync that ended moved Last Pull and the shots' own times: read them again. One that
	// began and ended between two polls never showed as running, and its times still moved.
	const synced = row ? `${row.state === "idle"}:${row.last_sync_attempt}:${row.last_pull}` : undefined;
	const lastSynced = useRef(synced);
	useEffect(() => {
		const before = lastSynced.current;
		lastSynced.current = synced;
		if (before !== undefined && synced !== undefined && before !== synced) void mutate();
	}, [synced, mutate]);

	const [settingsDirty, setSettingsDirty] = useState(false);
	const [resyncing, setResyncing] = useState(false);
	const [deleting, setDeleting] = useState(false);
	// shown from the press until the status says the same, so the toggle doesn't flick back
	const [enabling, setEnabling] = useState<boolean | null>(null);
	const menu = useRef<HTMLDivElement>(null);
	// what opened a dialog, which gets the focus back: the Actions button, or a button of a tab
	const launcher = useRef<HTMLElement | null>(null);

	function fromMenu() {
		launcher.current = menu.current?.querySelector("button") ?? null;
	}

	async function toggle(enabled: boolean) {
		setEnabling(enabled);
		if (await actions.setEnabled(name, enabled)) await refresh();
		setEnabling(null);
	}

	const breadcrumb: [string, string?][] = [["Connections", hrefFor("connections")], [name]];

	// Only without a Connection to show: one that was read stays, with what is being
	// changed in it, when reading it again fails.
	if (!detail) {
		const missing = readFailure(error).httpStatus === 404;
		return (
			<>
				<PageHeader breadcrumb={breadcrumb} title={name} />
				{error ? (
					<InlineNotification
						kind="error"
						lowContrast
						hideCloseButton
						title={missing ? `There is no connection ${name}.` : "The connection couldn't be loaded."}
						subtitle={missing ? "" : getErrorMessage(error, "Reload the page to try again.")}
					/>
				) : (
					<SkeletonText paragraph lineCount={4} />
				)}
			</>
		);
	}

	const enabled = Boolean(row ? row.enabled : detail.enabled);
	const state = row?.state ?? "idle";
	const busy = actions.busy.has(name);
	const health = row && status.now ? deriveHealth(row, status.now) : undefined;
	const href = (to: ConnectionTab | undefined) => hrefFor("connections", name, to ? { tab: to } : undefined);
	// Carbon's Tab takes no href of its own, but hands what it is given to the element it is `as`
	const link = (to: ConnectionTab | undefined) => ({
		as: "a" as const,
		href: href(to),
		onKeyDown: pressOnSpace,
	});

	// With unsaved settings it stays a button the keyboard reaches, and says why it does
	// nothing: a disabled one takes no focus, so its tooltip would never open.
	const test = (
		<Button
			kind="ghost"
			renderIcon={ConnectionSignal}
			disabled={check.busy}
			{...(settingsDirty ? { "aria-disabled": true, className: "cds--btn--disabled" } : {})}
			onClick={() => {
				if (!settingsDirty) check.run();
			}}
		>
			Test connection
		</Button>
	);

	return (
		// Controlled by the route: a tab is a link, and following it is what selects it. So a
		// tab can be bookmarked, and leaving unsaved settings is asked about like any link.
		<Tabs selectedIndex={Math.max(TABS.indexOf(tab), 0)} onChange={() => {}}>
			<PageHeader
				breadcrumb={breadcrumb}
				title={name}
				status={
					health ? (
						<StatusIndicator kind={health.kind} label={health.label} reason={health.reason ?? undefined} />
					) : (
						<StatusIndicator kind="unknown" label="Unknown" />
					)
				}
				subtitle={
					<>
						<code>{detail.server_url || "No server URL"}</code>
						<span>{describeSchedule(detail.sync_frequency, detail.cron_rule)}</span>
					</>
				}
				actions={
					<>
						<EnabledToggle
							id="connection-enabled"
							connection={name}
							enabled={enabling ?? enabled}
							disabled={busy}
							onToggle={(checked) => void toggle(checked)}
						/>
						{settingsDirty ? (
							<Tooltip description={DIRTY} align="bottom">
								{test}
							</Tooltip>
						) : (
							test
						)}
						<MenuButton ref={menu} label="Actions" kind="tertiary" menuAlignment="bottom-end">
							<MenuItem
								label="Resync everything…"
								disabled={state !== "idle" || busy}
								onClick={() => {
									fromMenu();
									setResyncing(true);
								}}
							/>
							<MenuItem
								label="Open in the desk"
								onClick={() => window.location.assign(deskFormUrl(CONNECTION, name))}
							/>
							<MenuItemDivider />
							<MenuItem
								label="Delete…"
								kind="danger"
								onClick={() => {
									fromMenu();
									setDeleting(true);
								}}
							/>
						</MenuButton>
						<BusyButton
							kind="primary"
							renderIcon={Renew}
							busy={busy || state !== "idle"}
							busyText={state === "queued" ? "Queued…" : "Syncing…"}
							disabled={!enabled}
							onClick={() => void actions.syncNow(name)}
						>
							Sync now
						</BusyButton>
					</>
				}
			>
				<TabList aria-label={`Sections of ${name}`} activation="manual">
					<Tab {...link(undefined)}>Activity</Tab>
					<Tab {...link("shots")}>{`Shots (${detail.shots.length})`}</Tab>
					<Tab {...link("links")}>Linked documents</Tab>
					<Tab {...link("settings")}>Settings</Tab>
				</TabList>
			</PageHeader>

			<Stack gap={5}>
				{error && (
					<InlineNotification
						kind="warning"
						lowContrast
						hideCloseButton
						title="The connection couldn't be refreshed."
						subtitle={getErrorMessage(error, "What is shown may be out of date. It is tried again.")}
						style={{ maxInlineSize: "none" }}
					/>
				)}
				{(row?.problems ?? []).map((problem, index) => (
					<ActionableNotification
						// the list is the server's, in the shots' order: a place in it is a problem's own
						// oxlint-disable-next-line react/no-array-index-key
						key={`${index}:${problem.code}:${problem.doctype}:${problem.transform}`}
						inline
						kind="error"
						lowContrast
						hideCloseButton
						// it is news, not a question: the keyboard stays where it is
						hasFocus={false}
						role={NEWS}
						aria-label={`Problem with the shot of ${problem.doctype}`}
						title={`${problem.message}.`}
						subtitle={
							problem.doctype ? `The shot of ${problem.doctype} can't sync until this is put right.` : ""
						}
						{...(problem.transform
							? {
									actionButtonLabel: "Open the transform",
									onActionButtonClick: () => navigate(hrefFor("transforms", problem.transform ?? "")),
								}
							: {
									actionButtonLabel: "Open shots",
									onActionButtonClick: () => navigate(href("shots")),
								})}
						style={{ maxInlineSize: "none" }}
					/>
				))}
				{row && didNotFinish(row) && (
					<ActionableNotification
						inline
						kind="error"
						lowContrast
						hideCloseButton
						hasFocus={false}
						role={NEWS}
						aria-label="The last sync"
						title="The last sync did not finish."
						subtitle="Something stopped it before the end. The reason is in the desk's Error Log."
						actionButtonLabel="Open the Error Log"
						onActionButtonClick={() => window.location.assign("/desk/error-log")}
						style={{ maxInlineSize: "none" }}
					/>
				)}
				{!detail.has_secret && (
					<Callout
						kind="warning"
						lowContrast
						title="No secret is stored."
						subtitle="Requests are sent without credentials."
						{...(tab === "settings"
							? {}
							: {
									actionButtonLabel: "Open settings",
									onActionButtonClick: () => navigate(href("settings")),
								})}
						style={{ maxInlineSize: "none" }}
					/>
				)}
				{!enabled && (
					<Callout
						kind="info"
						lowContrast
						title="Paused:"
						subtitle="scheduled syncs and Sync now are off."
						style={{ maxInlineSize: "none" }}
					/>
				)}
				<CheckConnection check={check} canRetry={!settingsDirty} />
			</Stack>

			<TabPanels>
				<TabPanel style={PANEL}>
					{tab === undefined && (
						<ActivityTab
							connection={detail}
							status={row}
							now={status.now}
							tested={check.result?.ok === true}
							testing={check.busy}
							onTest={check.run}
						/>
					)}
				</TabPanel>
				<TabPanel style={PANEL}>
					{tab === "shots" && <ShotsTab connection={detail} status={row} onChanged={refreshed} />}
				</TabPanel>
				<TabPanel style={PANEL}>
					{tab === "links" && (
						<LinksTab connection={name} shotDoctypes={detail.shots.map((shot) => shot.dt)} query={query} />
					)}
				</TabPanel>
				<TabPanel style={PANEL}>
					{tab === "settings" && (
						<SettingsTab
							connection={detail}
							status={row}
							onSaved={refresh}
							onDirtyChange={setSettingsDirty}
							onDelete={(from) => {
								launcher.current = from;
								setDeleting(true);
							}}
						/>
					)}
				</TabPanel>
			</TabPanels>

			<ResyncConnection
				open={resyncing}
				connection={name}
				busy={busy}
				launcherButtonRef={launcher}
				onConfirm={() => {
					void actions.resync(name).then((done) => {
						if (done) setResyncing(false);
					});
				}}
				onClose={() => setResyncing(false)}
			/>
			<DeleteConnection
				open={deleting}
				connection={name}
				launcherButtonRef={launcher}
				onClose={() => setDeleting(false)}
				onDeleted={() => {
					showToast({ kind: "success", title: `${name} was deleted.` });
					// not a link's click: there is nothing left here to ask about leaving
					window.location.hash = hrefFor("connections");
				}}
			/>
		</Tabs>
	);
}
