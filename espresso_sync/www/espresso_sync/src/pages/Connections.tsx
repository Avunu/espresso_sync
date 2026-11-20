// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useRef, useState } from "react";
import {
	Button,
	DataTable,
	DataTableSkeleton,
	Dropdown,
	InlineNotification,
	Link,
	OverflowMenu,
	OverflowMenuItem,
	Table,
	TableBatchAction,
	TableBatchActions,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableHeader,
	TableRow,
	TableSelectAll,
	TableSelectRow,
	TableToolbar,
	TableToolbarContent,
	TableToolbarSearch,
} from "@carbon/react";
import { Add, ConnectionSignal, PauseOutline, PlayOutline, Renew } from "@carbon/react/icons";
import { hostOf } from "../../../../public/js/portal/connectionForm.ts";
import { describeSchedule } from "../../../../public/js/portal/datetime.ts";
import { deriveHealth, type Health, needsAttention } from "../../../../public/js/portal/health.ts";
import { DateTime } from "../components/DateTime";
import { EmptyState } from "../components/EmptyState";
import { EnabledToggle } from "../components/EnabledToggle";
import { PageHeader } from "../components/PageHeader";
import { StatusIndicator } from "../components/StatusIndicator";
import { CONNECTION, type StatusRow } from "../data/api";
import { useConnectionStatus } from "../data/useConnectionStatus";
import { useSyncActions } from "../data/useSyncActions";
import { useToasts } from "../portal/Toasts";
import { getErrorMessage } from "../portal/useBackendCall";
import { deskFormUrl, hrefFor, replaceQuery } from "../route";
import { DeleteConnection, ResyncConnection } from "./connection/DeleteConnection";
import { NewConnection } from "./connection/NewConnection";

export interface ConnectionsProps {
	/** The route's query: `health` (attention or paused) filters, `new=1` opens the dialog. */
	query: Readonly<Record<string, string>>;
}

const HEADERS = [
	{ key: "name", header: "Name" },
	{ key: "health", header: "Health" },
	{ key: "server", header: "Server" },
	{ key: "schedule", header: "Schedule" },
	{ key: "shots", header: "Shots" },
	{ key: "last_sync", header: "Last sync" },
	{ key: "enabled", header: "Enabled" },
];

const DESCRIPTION =
	"Each connection holds an API's address and credentials, and the shots that sync its DocTypes through transforms.";

/** What `?health=` narrows the list to. */
const HEALTH_FILTERS = [
	{ id: "", text: "All" },
	{ id: "attention", text: "Needs attention" },
	{ id: "paused", text: "Paused" },
];
type HealthFilter = (typeof HEALTH_FILTERS)[number];

const UNKNOWN: Health = { kind: "unknown", label: "Unknown", reason: null };

interface ConnectionCellProps {
	row: StatusRow;
	column: string;
	health: Health;
	now: string | undefined;
	/** What the toggle shows: the press, until the status says the same. */
	enabled: boolean;
	busy: boolean;
	onToggle: (enabled: boolean) => void;
}

function ConnectionCell({ row, column, health, now, enabled, busy, onToggle }: ConnectionCellProps) {
	switch (column) {
		case "name":
			return (
				// a long name wraps, so the columns after it stay in the table
				<Link href={hrefFor("connections", row.name)} className="es-long-name">
					{row.name}
				</Link>
			);
		case "health":
			return <StatusIndicator kind={health.kind} label={health.label} reason={health.reason ?? undefined} />;
		case "server":
			return <code>{hostOf(row.server_url ?? "") || row.server_url || "—"}</code>;
		case "schedule":
			return <>{describeSchedule(row.sync_frequency, row.cron_rule)}</>;
		case "shots":
			return <Link href={hrefFor("connections", row.name, { tab: "shots" })}>{row.shots}</Link>;
		case "last_sync":
			return <DateTime value={row.last_pull} now={now} />;
		case "enabled":
			return (
				<EnabledToggle
					id={`connection-enabled-${row.name}`}
					connection={row.name}
					enabled={enabled}
					disabled={busy}
					onToggle={onToggle}
				/>
			);
		default:
			return null;
	}
}

/** `#/connections`: every Connection, with its health and what can be done with it. */
export function Connections({ query }: ConnectionsProps) {
	const { rows, now, error, isLoading, mutate } = useConnectionStatus();
	const actions = useSyncActions(mutate);
	const showToast = useToasts();
	const [search, setSearch] = useState("");
	// shown from the press until the status says the same, so a toggle doesn't flick back
	const [enabling, setEnabling] = useState<Readonly<Record<string, boolean>>>({});
	// a confirmation stays mounted on the Connection it was opened for while it closes
	const [resync, setResync] = useState<{ name: string; open: boolean } | null>(null);
	const [removal, setRemoval] = useState<{ name: string; open: boolean } | null>(null);
	const [batchBusy, setBatchBusy] = useState(false);
	const [creating, setCreating] = useState(false);
	// a new form each time it opens; mounted while closed, so the modal hands focus back to the button
	const [formKey, setFormKey] = useState(0);
	const newButton = useRef<HTMLButtonElement>(null);
	// what opened a confirmation, which gets the focus back: a row's menu button
	const launcher = useRef<HTMLElement | null>(null);

	const healthFilter = HEALTH_FILTERS.find((filter) => filter.id === query["health"]) ?? HEALTH_FILTERS[0];
	const wantsNew = query["new"] === "1";

	function setHealth(filter: HealthFilter | null | undefined) {
		replaceQuery({ health: filter?.id || undefined, new: wantsNew ? "1" : undefined });
	}

	function openNew() {
		setFormKey((key) => key + 1);
		setCreating(true);
	}

	function closeNew() {
		setCreating(false);
		// the link that opened it would open it again on a reload
		if (wantsNew) replaceQuery({ health: healthFilter?.id || undefined });
	}

	async function toggle(name: string, enabled: boolean) {
		setEnabling((current) => ({ ...current, [name]: enabled }));
		if (await actions.setEnabled(name, enabled)) await mutate();
		setEnabling(({ [name]: _done, ...others }) => others);
	}

	/** One action on each selected Connection it applies to, one after the other. */
	async function batch(names: string[], act: (name: string) => Promise<boolean>, done: () => void) {
		if (names.length === 0) {
			showToast({ kind: "info", title: "None of the selected connections needs that." });
			return;
		}
		setBatchBusy(true);
		for (const name of names) {
			// each waits for the one before: a toast apiece, in order
			// oxlint-disable-next-line no-await-in-loop
			await act(name);
		}
		setBatchBusy(false);
		done();
	}

	const newButtonNode = (
		<Button ref={newButton} kind="primary" renderIcon={Add} onClick={openNew}>
			New connection
		</Button>
	);

	const byName = new Map(rows.map((row) => [row.name, row]));
	const healthOf = (row: StatusRow) => (now ? deriveHealth(row, now) : UNKNOWN);
	const needle = search.trim().toLowerCase();
	const shown = rows.filter((row) => {
		if (healthFilter?.id === "attention" && !(now && needsAttention(row, now))) return false;
		if (healthFilter?.id === "paused" && row.enabled) return false;
		return !needle || `${row.name}\n${row.server_url ?? ""}`.toLowerCase().includes(needle);
	});

	let table;
	if (isLoading) {
		table = <DataTableSkeleton headers={HEADERS} columnCount={HEADERS.length + 2} rowCount={3} />;
		// only without rows to show: a poll that fails later keeps the table, and what is selected in it
	} else if (error && now === undefined) {
		table = (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title="The connections couldn't be loaded."
				subtitle={getErrorMessage(error, "Reload the page to try again.")}
			/>
		);
	} else if (rows.length === 0) {
		table = (
			<EmptyState icon={ConnectionSignal} title="No connections yet." action={newButtonNode}>
				A connection is an API to sync with: where it is, how to authenticate, and which DocTypes it syncs.
			</EmptyState>
		);
	} else {
		const tableRows = shown.map((row) => ({
			id: row.name,
			name: row.name,
			health: healthOf(row).label,
			server: hostOf(row.server_url ?? "") || (row.server_url ?? ""),
			schedule: describeSchedule(row.sync_frequency, row.cron_rule),
			shots: row.shots,
			last_sync: row.last_pull ?? "",
			enabled: row.enabled,
		}));
		table = (
			<DataTable rows={tableRows} headers={HEADERS} isSortable size="md">
				{({
					rows: sorted,
					headers,
					selectedRows,
					getTableProps,
					getTableContainerProps,
					getToolbarProps,
					getBatchActionProps,
					getSelectionProps,
					getHeaderProps,
					getRowProps,
					getCellProps,
				}) => {
					const batchProps = getBatchActionProps();
					const { size: toolbarSize, ...toolbarProps } = getToolbarProps();
					// the getters leave `undefined` where Carbon's own components take nothing at all
					const all = getSelectionProps();
					const selected = selectedRows.flatMap((row) => byName.get(row.id) ?? []);
					const clear = () => batchProps.onCancel();
					return (
						<TableContainer {...getTableContainerProps()}>
							<TableToolbar
								{...toolbarProps}
								{...(toolbarSize ? { size: toolbarSize } : {})}
								aria-label="Connections"
							>
								<TableBatchActions {...batchProps}>
									<TableBatchAction
										tabIndex={batchProps.shouldShowBatchActions ? 0 : -1}
										renderIcon={Renew}
										disabled={batchBusy}
										onClick={() => {
											const names = selected
												.filter((row) => row.enabled && row.state === "idle")
												.map((row) => row.name);
											void batch(names, actions.syncNow, clear);
										}}
									>
										Sync now
									</TableBatchAction>
									<TableBatchAction
										tabIndex={batchProps.shouldShowBatchActions ? 0 : -1}
										renderIcon={PauseOutline}
										disabled={batchBusy}
										onClick={() => {
											const names = selected.filter((row) => row.enabled).map((row) => row.name);
											void batch(names, (name) => actions.setEnabled(name, false), clear);
										}}
									>
										Pause
									</TableBatchAction>
									<TableBatchAction
										tabIndex={batchProps.shouldShowBatchActions ? 0 : -1}
										renderIcon={PlayOutline}
										disabled={batchBusy}
										onClick={() => {
											const names = selected.filter((row) => !row.enabled).map((row) => row.name);
											void batch(names, (name) => actions.setEnabled(name, true), clear);
										}}
									>
										Resume
									</TableBatchAction>
								</TableBatchActions>
								<TableToolbarContent aria-hidden={batchProps.shouldShowBatchActions}>
									<TableToolbarSearch
										persistent
										labelText="Search the connections"
										placeholder="Search by name or server"
										tabIndex={batchProps.shouldShowBatchActions ? -1 : 0}
										value={search}
										onChange={(_event, value) => setSearch(value ?? "")}
									/>
									<div style={{ inlineSize: "13rem", flexShrink: 0 }}>
										<Dropdown
											id="connections-health"
											size="lg"
											titleText="Health"
											hideLabel
											label="Health"
											items={HEALTH_FILTERS}
											itemToString={(item) => item?.text ?? ""}
											selectedItem={healthFilter}
											disabled={batchProps.shouldShowBatchActions}
											onChange={({ selectedItem }) => setHealth(selectedItem)}
										/>
									</div>
									{newButtonNode}
								</TableToolbarContent>
							</TableToolbar>
							<Table {...getTableProps()} aria-label="Connections">
								<TableHead>
									<TableRow>
										<TableSelectAll
											id={all.id}
											name={all.name}
											aria-label={all["aria-label"]}
											checked={Boolean(all.checked)}
											indeterminate={Boolean(all.indeterminate)}
											onSelect={all.onSelect}
										/>
										{headers.map((header) => {
											const { key, isSortable, ...headerProps } = getHeaderProps({
												header,
												isSortable: header.key !== "enabled",
											});
											return (
												<TableHeader key={key} {...headerProps} isSortable={Boolean(isSortable)}>
													{header.header}
												</TableHeader>
											);
										})}
										<TableHeader aria-label="Actions" />
									</TableRow>
								</TableHead>
								<TableBody>
									{sorted.length === 0 && (
										<TableRow>
											<TableCell colSpan={headers.length + 2}>
												<EmptyState
													title="No connections match these filters."
													action={
														<Button
															kind="tertiary"
															size="sm"
															onClick={() => {
																setSearch("");
																setHealth(null);
															}}
														>
															Clear filters
														</Button>
													}
												/>
											</TableCell>
										</TableRow>
									)}
									{sorted.map((tableRow) => {
										const record = byName.get(tableRow.id);
										if (!record) return null;
										const { key: rowKey, ...rowProps } = getRowProps({ row: tableRow });
										const one = getSelectionProps({ row: tableRow });
										const busy = actions.busy.has(record.name) || batchBusy;
										return (
											<TableRow key={rowKey} {...rowProps}>
												<TableSelectRow
													id={one.id}
													name={one.name}
													aria-label={`Select ${record.name}`}
													checked={Boolean(one.checked)}
													onSelect={one.onSelect}
												/>
												{tableRow.cells.map((cell) => {
													const { key: cellKey, ...cellProps } = getCellProps({ cell });
													return (
														<TableCell key={cellKey} {...cellProps}>
															<ConnectionCell
																row={record}
																column={cell.info.header}
																health={healthOf(record)}
																now={now}
																enabled={enabling[record.name] ?? Boolean(record.enabled)}
																busy={busy}
																onToggle={(enabled) => void toggle(record.name, enabled)}
															/>
														</TableCell>
													);
												})}
												<TableCell className="cds--table-column-menu" style={{ inlineSize: "4rem" }}>
													<OverflowMenu
														aria-label={`Actions for ${record.name}`}
														iconDescription={`Actions for ${record.name}`}
														size="sm"
														flipped
														onClick={(event?: { currentTarget?: unknown }) => {
															if (event?.currentTarget instanceof HTMLElement) {
																launcher.current = event.currentTarget;
															}
														}}
													>
														<OverflowMenuItem
															itemText="Sync now"
															disabled={!record.enabled || record.state !== "idle" || busy}
															onClick={() => void actions.syncNow(record.name)}
														/>
														<OverflowMenuItem
															itemText="Resync everything…"
															disabled={record.state !== "idle" || busy}
															onClick={() => setResync({ name: record.name, open: true })}
														/>
														<OverflowMenuItem
															itemText="Open settings"
															href={hrefFor("connections", record.name, { tab: "settings" })}
														/>
														<OverflowMenuItem
															itemText="Open in the desk"
															href={deskFormUrl(CONNECTION, record.name)}
														/>
														<OverflowMenuItem
															itemText="Delete…"
															isDelete
															hasDivider
															onClick={() => setRemoval({ name: record.name, open: true })}
														/>
													</OverflowMenu>
												</TableCell>
											</TableRow>
										);
									})}
								</TableBody>
							</Table>
						</TableContainer>
					);
				}}
			</DataTable>
		);
	}

	return (
		<>
			<PageHeader breadcrumb={[]} title="Connections" subtitle={DESCRIPTION} />
			{Boolean(error) && now !== undefined && (
				<InlineNotification
					kind="warning"
					lowContrast
					hideCloseButton
					title="The connections couldn't be refreshed."
					subtitle={getErrorMessage(error, "What is shown may be out of date. It is tried again.")}
					style={{ maxInlineSize: "none", marginBlockEnd: "var(--cds-spacing-05)" }}
				/>
			)}
			{table}
			<NewConnection
				key={formKey}
				open={creating || wantsNew}
				launcherButtonRef={newButton}
				onClose={closeNew}
			/>
			{resync && (
				<ResyncConnection
					open={resync.open}
					connection={resync.name}
					busy={actions.busy.has(resync.name)}
					launcherButtonRef={launcher}
					onConfirm={() => {
						void actions.resync(resync.name).then((done) => {
							if (done) setResync({ name: resync.name, open: false });
						});
					}}
					onClose={() => setResync({ name: resync.name, open: false })}
				/>
			)}
			{removal && (
				<DeleteConnection
					open={removal.open}
					connection={removal.name}
					launcherButtonRef={launcher}
					onClose={() => setRemoval({ name: removal.name, open: false })}
					onDeleted={() => {
						showToast({ kind: "success", title: `${removal.name} was deleted.` });
						setRemoval({ name: removal.name, open: false });
						void mutate();
					}}
				/>
			)}
		</>
	);
}
