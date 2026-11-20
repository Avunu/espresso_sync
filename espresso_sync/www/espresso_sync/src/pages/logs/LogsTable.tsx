// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type CSSProperties, useEffect, useRef, useState } from "react";
import {
	Button,
	ContentSwitcher,
	DataTable,
	DataTableSkeleton,
	DismissibleTag,
	Dropdown,
	IconButton,
	InlineLoading,
	InlineNotification,
	Link,
	Pagination,
	Stack,
	Switch,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableExpandedRow,
	TableExpandHeader,
	TableExpandRow,
	TableHead,
	TableHeader,
	TableRow,
	TableToolbar,
	TableToolbarAction,
	TableToolbarContent,
	TableToolbarMenu,
	TableToolbarSearch,
	Tag,
} from "@carbon/react";
import { Renew } from "@carbon/react/icons";
import { type Filter, useFrappeGetDocCount, useFrappeGetDocList } from "frappe-react-sdk";
import type { Severity } from "../../../../../public/js/editor/diagnostics.ts";
import {
	FILTER_KEYS,
	filtersFromQuery,
	frappeFilters,
	lastError,
	type LogFilters,
	queryFromFilters,
} from "../../../../../public/js/portal/logs.ts";
import { DateTime } from "../../components/DateTime";
import { EmptyState } from "../../components/EmptyState";
import { StatusIndicator } from "../../components/StatusIndicator";
import { PULL_LOG, PULL_LOG_FIELDS, type PullLogRow } from "../../data/api";
import { useConnectionStatus } from "../../data/useConnectionStatus";
import { getErrorMessage, parseJson } from "../../portal/useBackendCall";
import { hrefFor, replaceQuery } from "../../route";
import { useSessionRead } from "../../useSessionRead";
import { SeverityIcon } from "../SeverityIcon";
import { ClearLogsModal } from "./ClearLogsModal";
import { RetentionModal } from "./RetentionModal";

export interface LogsTableProps {
	/** Filters the table always applies and offers no control for: a Connection's own log. */
	fixed: LogFilters;
	/** Whether to show the Connection column and filter: not on a Connection's own page. */
	showConnection: boolean;
	/** The route's query, which the other filters and the page number are read from. */
	query?: Readonly<Record<string, string>> | undefined;
	/** Whether a filter change is written back to the route's query (replaceQuery). */
	syncQuery?: boolean | undefined;
}

const PAGE_SIZES = [25, 50, 100];
/** While a Connection in scope is syncing, the entries are read again this often. */
const RUNNING_MS = 10_000;
/** A search is sent this long after the last key. */
const SEARCH_MS = 400;

/** The periods `since` can name, as the Period filter words them. */
const PERIODS: [since: string, label: string][] = [
	["1h", "Last hour"],
	["24h", "Last 24 hours"],
	["7d", "Last 7 days"],
	["attempt", "Since the last sync"],
];

const FILTER_ROW: CSSProperties = {
	display: "flex",
	flexWrap: "wrap",
	gap: "var(--cds-spacing-05)",
	alignItems: "flex-end",
	// in line with the table's own edges
	paddingBlock: "var(--cds-spacing-05)",
};
const TAG_ROW: CSSProperties = {
	display: "flex",
	flexWrap: "wrap",
	gap: "var(--cds-spacing-02)",
	alignItems: "center",
	paddingBlockEnd: "var(--cds-spacing-03)",
};
const SECONDARY: CSSProperties = { color: "var(--cds-text-secondary)" };

/** The filters and the page the table is on. */
interface View {
	filters: LogFilters;
	page: number;
}

function viewOf(query: Readonly<Record<string, string>>): View {
	const page = Number(query["page"]);
	return { filters: filtersFromQuery(query), page: Number.isInteger(page) && page > 0 ? page : 1 };
}

/** The view, kept in the route's query when `syncQuery` is set (so a link carries it), and
 * in the table otherwise. A key of the query that is not the table's stays as it is. */
function useView(
	query: Readonly<Record<string, string>> | undefined,
	syncQuery: boolean,
): [View, (next: View) => void] {
	const [local, setLocal] = useState(() => viewOf(query ?? {}));
	if (!syncQuery || !query) return [local, setLocal];
	const write = (next: View) => {
		const kept: Record<string, string | undefined> = { ...query };
		for (const key of FILTER_KEYS) delete kept[key];
		replaceQuery({
			...kept,
			...queryFromFilters(next.filters),
			page: next.page > 1 ? String(next.page) : undefined,
		});
	};
	return [viewOf(query), write];
}

function periodLabel(since: string): string {
	return PERIODS.find(([value]) => value === since)?.[1] ?? `On ${since}`;
}

/** A set filter as its tag reads. */
function tagText(key: keyof LogFilters, value: string): string {
	switch (key) {
		case "connection":
			return `Connection: ${value}`;
		case "status":
			return `Status: ${value}`;
		case "direction":
			return `Direction: ${value}`;
		case "doctype":
			return `DocType: ${value}`;
		case "transform":
			return `Transform: ${value}`;
		case "doc":
			return `Document contains: ${value}`;
		case "docs":
			return "Documents only, no requests";
		case "since":
			return `Period: ${periodLabel(value)}`;
		case "code":
			// the code is inside the entry's diagnostics, which the server cannot filter on
			return `Error code: ${value} (within this page only)`;
	}
}

/** The path and query of a request's URL, or the URL as it is when it does not parse. */
export function pathOf(url: string): string {
	try {
		const { pathname, search } = new URL(url);
		return pathname + search;
	} catch {
		return url;
	}
}

/** One diagnostic of a log entry, as the sync wrote it. */
export interface LogDiagnostic {
	/** Its place in the entry's list, which is all that tells two alike apart. */
	id: string;
	severity: Severity;
	code: string;
	message: string;
	/** Where in the object or the document, when the finding has a place. */
	path: string;
}

/** An entry's `diagnostics` (JSON text, or already parsed) as a list. Read, not asserted:
 * what is not a diagnostic is left out. */
export function readDiagnostics(diagnostics: unknown): LogDiagnostic[] {
	const list = typeof diagnostics === "string" ? parseJson(diagnostics) : diagnostics;
	if (!Array.isArray(list)) return [];
	const found: LogDiagnostic[] = [];
	for (const entry of list) {
		const item: unknown = entry;
		if (typeof item !== "object" || item === null) continue;
		const { severity, code, message, path, rule } = item as Record<string, unknown>;
		const where = typeof path === "string" && path ? path : rule;
		found.push({
			id: String(found.length),
			severity: severity === "error" || severity === "warning" ? severity : "info",
			code: typeof code === "string" ? code : "",
			message: typeof message === "string" ? message : "",
			path: typeof where === "string" ? where : "",
		});
	}
	return found;
}

interface LogDiagnosticsProps {
	diagnostics: LogDiagnostic[];
}

/** What the sync found about an entry: the schema's findings, then why it failed. */
export function LogDiagnostics({ diagnostics }: LogDiagnosticsProps) {
	if (diagnostics.length === 0) return <p style={SECONDARY}>No diagnostics were logged.</p>;
	return (
		<Table size="sm" aria-label="Diagnostics">
			<TableHead>
				<TableRow>
					<TableHeader>Severity</TableHeader>
					<TableHeader>Code</TableHeader>
					<TableHeader>Finding</TableHeader>
					<TableHeader>Field</TableHeader>
				</TableRow>
			</TableHead>
			<TableBody>
				{diagnostics.map((found) => (
					<TableRow key={found.id}>
						<TableCell>
							<SeverityIcon severity={found.severity} /> {found.severity}
						</TableCell>
						<TableCell>
							<code>{found.code}</code>
						</TableCell>
						<TableCell style={{ overflowWrap: "anywhere" }}>{found.message}</TableCell>
						<TableCell>{found.path ? <code>{found.path}</code> : "—"}</TableCell>
					</TableRow>
				))}
			</TableBody>
		</Table>
	);
}

interface LogCellProps {
	row: PullLogRow;
	column: string;
	now: string | undefined;
}

function LogCell({ row, column, now }: LogCellProps) {
	switch (column) {
		case "when":
			return (
				<Link href={hrefFor("logs", row.name)}>
					<DateTime value={row.creation} now={now} />
				</Link>
			);
		case "status":
			return row.sync_status === "Failure" ? (
				<StatusIndicator kind="failure" label="Failure" />
			) : (
				<StatusIndicator kind="success" label="Success" />
			);
		case "direction":
			if (!row.sync_direction) return <>—</>;
			return (
				<Tag size="sm" type={row.sync_direction === "Import" ? "cyan" : "purple"}>
					{row.sync_direction}
				</Tag>
			);
		case "connection":
			if (!row.sync_connection) return <>—</>;
			return (
				<Link href={hrefFor("connections", row.sync_connection)} className="es-long-name">
					{row.sync_connection}
				</Link>
			);
		case "document":
			if (row.sync_doc) {
				return (
					<>
						<span style={SECONDARY}>{row.sync_doctype}</span> {row.sync_doc}
					</>
				);
			}
			return (
				<>
					<span style={SECONDARY}>Request</span>{" "}
					{row.request_type && (
						<Tag size="sm" type="gray">
							{row.request_type}
						</Tag>
					)}{" "}
					{row.url && <code style={{ overflowWrap: "anywhere" }}>{pathOf(row.url)}</code>}
				</>
			);
		case "error": {
			const error = lastError(row.diagnostics);
			if (!error) return <>—</>;
			return (
				// the widest column: long names in the others don't squeeze it to a word a line
				<span style={{ display: "inline-block", minInlineSize: "16rem", overflowWrap: "break-word" }}>
					<code>{error.code}</code> {error.message}
				</span>
			);
		}
		case "transform":
			if (!row.transform) return <>—</>;
			return (
				<Link href={hrefFor("transforms", row.transform)} className="es-long-name">
					{row.transform}
				</Link>
			);
		default:
			return null;
	}
}

/** DataTable's toolbar props, without the size it leaves undefined for a table of the default size. */
function toolbarProps({ size, ...rest }: { size: "xs" | "sm" | undefined; [key: string]: unknown }) {
	return size ? { ...rest, size } : rest;
}

/** One choice of a filter's Dropdown; the first has no value, and stands for no filter. */
interface Choice {
	value: string;
	text: string;
}

interface FilterDropdownProps {
	id: string;
	title: string;
	/** What the choice of no filter reads: "All connections". */
	all: string;
	choices: Choice[];
	value: string | undefined;
	onChange: (value: string | undefined) => void;
}

function FilterDropdown({ id, title, all, choices, value, onChange }: FilterDropdownProps) {
	const none: Choice = { value: "", text: all };
	// a value from a link that is not among the choices is still what is filtered by
	const known = !value || choices.some((choice) => choice.value === value);
	const items = [none, ...choices, ...(known || !value ? [] : [{ value, text: value }])];
	return (
		<div style={{ minInlineSize: "11rem" }}>
			<Dropdown
				id={id}
				size="sm"
				titleText={title}
				label={all}
				items={items}
				itemToString={(item) => item?.text ?? ""}
				selectedItem={items.find((item) => item.value === (value ?? "")) ?? none}
				onChange={({ selectedItem }) => onChange(selectedItem?.value || undefined)}
			/>
		</div>
	);
}

/** The Pull Log as a server-paged table with its filters. */
export function LogsTable({ fixed, showConnection, query, syncQuery }: LogsTableProps) {
	const [view, setView] = useView(query, Boolean(syncQuery));
	const [pageSize, setPageSize] = useState(PAGE_SIZES[0] ?? 25);
	// a fixed filter wins over the same one in a link
	const filters: LogFilters = { ...view.filters, ...fixed };
	const offered = (key: keyof LogFilters) => fixed[key] === undefined;
	const set = FILTER_KEYS.filter((key) => offered(key) && view.filters[key]);
	const narrowed = set.length > 0 || FILTER_KEYS.some((key) => key !== "connection" && fixed[key]);

	const status = useConnectionStatus(fixed.connection);
	const inScope = filters.connection
		? status.rows.filter((row) => row.name === filters.connection)
		: status.rows;
	const running = inScope.some((row) => row.state === "running");
	const lastAttempt = filters.connection ? inScope[0]?.last_sync_attempt : undefined;

	// The time a period is counted back from. It is the server's, and it is held still
	// while the filters stay as they are: a period that moved with every poll of the
	// status would be a new list each time.
	const [anchor, setAnchor] = useState<string | undefined>(undefined);
	const [sinceSeen, setSinceSeen] = useState(filters.since);
	if (status.now && (anchor === undefined || sinceSeen !== filters.since)) {
		setAnchor(status.now);
		setSinceSeen(filters.since);
	}
	// a period needs the server's time (and "attempt" the Connection's) before it can be asked for
	const ready = !filters.since || anchor !== undefined;

	// the operators frappeFilters() uses are all ones the REST API takes
	const listFilters = frappeFilters(filters, anchor ?? "", lastAttempt) as Filter<PullLogRow>[];
	const polling = { keepPreviousData: true, refreshInterval: running ? RUNNING_MS : 0 };
	const list = useFrappeGetDocList<PullLogRow>(
		PULL_LOG,
		{
			fields: [...PULL_LOG_FIELDS],
			filters: listFilters,
			orderBy: { field: "creation", order: "desc" },
			limit_start: (view.page - 1) * pageSize,
			limit: pageSize,
		},
		ready ? undefined : null,
		polling,
	);
	useSessionRead(list.data, list.error);
	const count = useFrappeGetDocCount<PullLogRow>(
		PULL_LOG,
		listFilters,
		false,
		ready ? undefined : null,
		polling,
	);
	useSessionRead(count.data, count.error);

	// the DocTypes there are entries of, for the filter: of the Connection in scope
	const doctypes = useFrappeGetDocList<{ sync_doctype: string | null }>(
		PULL_LOG,
		{
			fields: ["sync_doctype"],
			filters: filters.connection ? [["sync_connection", "=", filters.connection]] : [],
			groupBy: "sync_doctype",
			orderBy: { field: "sync_doctype", order: "asc" },
			limit: 200,
		},
		offered("doctype") ? undefined : null,
		{ revalidateOnFocus: false },
	);
	useSessionRead(doctypes.data, doctypes.error);

	const mutateList = list.mutate;
	const mutateCount = count.mutate;
	// the sync's last entries are written after the last poll of it running
	const wasRunning = useRef(running);
	useEffect(() => {
		if (wasRunning.current && !running) {
			void mutateList();
			void mutateCount();
		}
		wasRunning.current = running;
	}, [running, mutateList, mutateCount]);

	// a page past the end (entries were cleared, or the link is old) goes back to the first
	const pastEnd = view.page > 1 && list.data?.length === 0 && !list.isValidating;
	useEffect(() => {
		if (pastEnd) setView({ filters: view.filters, page: 1 });
	}, [pastEnd, setView, view.filters]);

	function change(key: keyof LogFilters, value: string | undefined) {
		const next: LogFilters = { ...view.filters };
		if (value) next[key] = value;
		else delete next[key];
		// "since the last sync" is one Connection's: without the Connection it means nothing
		if (key === "connection" && !value && next.since === "attempt") delete next.since;
		setView({ filters: next, page: 1 });
	}

	// The search box keeps its own text (Carbon's is uncontrolled), and is made anew when
	// the document filter changes from elsewhere: its tag is closed, a link is followed.
	const [box, setBox] = useState({ key: 0, doc: view.filters.doc });
	if (box.doc !== view.filters.doc) setBox({ key: box.key + 1, doc: view.filters.doc });
	const timer = useRef<number | undefined>(undefined);
	const search = useRef<(text: string) => void>(() => {});
	useEffect(() => {
		search.current = (text) => {
			const doc = text.trim() || undefined;
			// Carbon reports the text it starts with as a change: that is no new search
			if (doc === view.filters.doc) return;
			setBox((current) => ({ key: current.key, doc }));
			change("doc", doc);
		};
	});
	useEffect(() => () => window.clearTimeout(timer.current), []);

	function refresh() {
		if (status.now) setAnchor(status.now);
		void status.mutate();
		void mutateList();
		void mutateCount();
	}

	const [retention, setRetention] = useState(false);
	const [clearing, setClearing] = useState(false);
	// the toolbar menu's button, which a dialog opened from the menu hands the focus back to
	const menuButton = useRef<HTMLElement | null>(null);

	const headers = [
		{ key: "when", header: "When" },
		{ key: "status", header: "Status" },
		{ key: "direction", header: "Direction" },
		...(showConnection ? [{ key: "connection", header: "Connection" }] : []),
		{ key: "document", header: "Document" },
		{ key: "error", header: "Error" },
		{ key: "transform", header: "Transform" },
	];

	const entries = list.data ?? [];
	// an entry with no error diagnostic is under "unknown", as failure_groups has it
	const shown = filters.code
		? entries.filter((row) => (lastError(row.diagnostics)?.code ?? "unknown") === filters.code)
		: entries;
	const byId = new Map(shown.map((row) => [row.name, row]));
	const rows = shown.map((row) => ({ id: row.name }));
	const total = count.data ?? entries.length;
	const failed = list.error ?? (ready ? undefined : status.error);
	const loading = !failed && (!ready || (list.isLoading && !list.data));

	const periods: Choice[] = PERIODS.filter(([value]) => value !== "attempt" || filters.connection).map(
		([value, text]) => ({ value, text }),
	);
	if (filters.since && !periods.some((period) => period.value === filters.since)) {
		periods.push({ value: filters.since, text: periodLabel(filters.since) });
	}
	const statusIndex = filters.status === "Failure" ? 1 : filters.status === "Success" ? 2 : 0;

	return (
		<>
			<DataTable rows={rows} headers={headers} size="md">
				{({
					rows: tableRows,
					headers: tableHeaders,
					getTableProps,
					getTableContainerProps,
					getToolbarProps,
					getHeaderProps,
					getExpandHeaderProps,
					getRowProps,
					getExpandedRowProps,
					getCellProps,
				}) => (
					<TableContainer {...getTableContainerProps()}>
						<div style={FILTER_ROW}>
							{offered("status") && (
								<ContentSwitcher
									aria-label="Status"
									size="sm"
									selectedIndex={statusIndex}
									style={{ inlineSize: "18rem" }}
									onChange={({ name }) => change("status", name === "all" ? undefined : String(name))}
								>
									<Switch name="all" text="All" />
									<Switch name="Failure" text="Failures" />
									<Switch name="Success" text="Success" />
								</ContentSwitcher>
							)}
							{showConnection && offered("connection") && (
								<FilterDropdown
									id="log-filter-connection"
									title="Connection"
									all="All connections"
									choices={status.rows.map((row) => ({ value: row.name, text: row.name }))}
									value={filters.connection}
									onChange={(value) => change("connection", value)}
								/>
							)}
							{offered("direction") && (
								<FilterDropdown
									id="log-filter-direction"
									title="Direction"
									all="Both directions"
									choices={[
										{ value: "Import", text: "Import" },
										{ value: "Export", text: "Export" },
									]}
									value={filters.direction}
									onChange={(value) => change("direction", value)}
								/>
							)}
							{offered("doctype") && (
								<FilterDropdown
									id="log-filter-doctype"
									title="DocType"
									all="All DocTypes"
									choices={(doctypes.data ?? []).flatMap((row) =>
										row.sync_doctype ? [{ value: row.sync_doctype, text: row.sync_doctype }] : [],
									)}
									value={filters.doctype}
									onChange={(value) => change("doctype", value)}
								/>
							)}
							{offered("since") && (
								<FilterDropdown
									id="log-filter-period"
									title="Period"
									all="Any time"
									choices={periods}
									value={filters.since}
									onChange={(value) => change("since", value)}
								/>
							)}
						</div>
						{set.length > 0 && (
							<div style={TAG_ROW}>
								{set.map((key) => (
									<DismissibleTag
										key={key}
										type={key === "code" ? "red" : "gray"}
										text={tagText(key, view.filters[key] ?? "")}
										title="Remove filter"
										onClose={() => change(key, undefined)}
									/>
								))}
								<Button kind="ghost" size="sm" onClick={() => setView({ filters: {}, page: 1 })}>
									Clear filters
								</Button>
							</div>
						)}
						<TableToolbar {...toolbarProps(getToolbarProps())} aria-label="Sync log actions">
							<TableToolbarContent>
								{running && (
									<InlineLoading
										description="Updating while a sync runs"
										style={{ inlineSize: "auto", paddingInline: "var(--cds-spacing-05)" }}
									/>
								)}
								{offered("doc") && (
									<TableToolbarSearch
										key={box.key}
										persistent
										labelText="Find entries by document name"
										placeholder="Find a document"
										defaultValue={view.filters.doc ?? ""}
										onChange={(_event, value) => {
											window.clearTimeout(timer.current);
											timer.current = window.setTimeout(() => search.current(value ?? ""), SEARCH_MS);
										}}
									/>
								)}
								<IconButton kind="ghost" label="Refresh" align="bottom" onClick={refresh}>
									<Renew />
								</IconButton>
								<span
									style={{ display: "contents" }}
									ref={(node) => {
										menuButton.current = node?.querySelector("button") ?? null;
									}}
								>
									<TableToolbarMenu iconDescription="Log options">
										<TableToolbarAction onClick={() => setRetention(true)}>Log retention…</TableToolbarAction>
										<TableToolbarAction onClick={() => setClearing(true)}>Clear entries…</TableToolbarAction>
									</TableToolbarMenu>
								</span>
							</TableToolbarContent>
						</TableToolbar>
						{failed ? (
							<InlineNotification
								kind="error"
								lowContrast
								hideCloseButton
								title="The sync log couldn't be loaded."
								subtitle={getErrorMessage(failed, "Reload the page to try again.")}
							/>
						) : loading ? (
							<DataTableSkeleton
								headers={headers}
								columnCount={headers.length}
								rowCount={5}
								showHeader={false}
								showToolbar={false}
							/>
						) : (
							<Table {...getTableProps()} aria-label="Sync log">
								<TableHead>
									<TableRow>
										<TableExpandHeader {...getExpandHeaderProps()} />
										{tableHeaders.map((header) => {
											const { key, ...headerProps } = getHeaderProps({ header });
											return (
												<TableHeader key={key} {...headerProps} isSortable={false}>
													{header.header}
												</TableHeader>
											);
										})}
									</TableRow>
								</TableHead>
								<TableBody>
									{tableRows.length === 0 && (
										<TableRow>
											<TableCell colSpan={tableHeaders.length + 1}>
												{narrowed ? (
													<EmptyState
														title="No entries match these filters."
														action={
															set.length > 0 && (
																<Button
																	kind="tertiary"
																	size="sm"
																	onClick={() => setView({ filters: {}, page: 1 })}
																>
																	Clear filters
																</Button>
															)
														}
													/>
												) : (
													<EmptyState title="No log entries yet.">
														A sync writes one per request and per document.
													</EmptyState>
												)}
											</TableCell>
										</TableRow>
									)}
									{tableRows.map((tableRow) => {
										const record = byId.get(tableRow.id);
										if (!record) return null;
										const { key, ...rowProps } = getRowProps({ row: tableRow });
										return [
											<TableExpandRow key={key} {...rowProps}>
												{tableRow.cells.map((cell) => {
													const { key: cellKey, ...cellProps } = getCellProps({ cell });
													return (
														<TableCell key={cellKey} {...cellProps}>
															<LogCell row={record} column={cell.info.header} now={status.now} />
														</TableCell>
													);
												})}
											</TableExpandRow>,
											<TableExpandedRow
												key={`${key}-expanded`}
												colSpan={tableHeaders.length + 1}
												{...getExpandedRowProps({ row: tableRow })}
											>
												{tableRow.isExpanded && (
													<Stack gap={5}>
														<LogDiagnostics diagnostics={readDiagnostics(record.diagnostics)} />
														<Link href={hrefFor("logs", record.name)}>Open entry</Link>
													</Stack>
												)}
											</TableExpandedRow>,
										];
									})}
								</TableBody>
							</Table>
						)}
						{!failed && !loading && (
							<Pagination
								page={view.page}
								pageSize={pageSize}
								pageSizes={PAGE_SIZES}
								totalItems={total}
								itemsPerPageText="Entries per page:"
								onChange={(next) => {
									if (next.pageSize !== pageSize) {
										setPageSize(next.pageSize);
										setView({ filters: view.filters, page: 1 });
									} else if (next.page !== view.page) {
										setView({ filters: view.filters, page: next.page });
									}
								}}
							/>
						)}
					</TableContainer>
				)}
			</DataTable>
			<RetentionModal open={retention} launcherButtonRef={menuButton} onClose={() => setRetention(false)} />
			<ClearLogsModal
				open={clearing}
				filters={filters}
				allowAll={!fixed.connection}
				launcherButtonRef={menuButton}
				onClose={() => setClearing(false)}
				onCleared={refresh}
			/>
		</>
	);
}
