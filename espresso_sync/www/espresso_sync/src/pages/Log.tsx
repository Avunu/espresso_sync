// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import {
	Button,
	InlineNotification,
	Link,
	SkeletonText,
	Stack,
	Tab,
	TabList,
	TabPanel,
	TabPanels,
	Tabs,
	Tag,
} from "@carbon/react";
import { Launch, Renew } from "@carbon/react/icons";
import { useFrappeGetDoc } from "frappe-react-sdk";
import { ERROR_HINTS, lastError } from "../../../../public/js/portal/logs.ts";
import { BusyButton } from "../components/BusyButton";
import { DateTime } from "../components/DateTime";
import { DescriptionList } from "../components/DescriptionList";
import { JsonBlock } from "../components/JsonBlock";
import { PageHeader } from "../components/PageHeader";
import { StatusIndicator } from "../components/StatusIndicator";
import { type Direction, PULL_LOG } from "../data/api";
import { useConnectionStatus } from "../data/useConnectionStatus";
import { useSyncActions } from "../data/useSyncActions";
import { getErrorMessage, readFailure } from "../portal/useBackendCall";
import { deskFormUrl, hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";
import { LogDiagnostics, pathOf, readDiagnostics } from "./logs/LogsTable";

export interface LogProps {
	/** The Pull Log entry's name. */
	name: string;
}

/** A Pull Log entry as the REST API answers with it: the JSON fields as text. */
interface PullLogDoc {
	name: string;
	creation: string;
	sync_connection: string | null;
	sync_doctype: string | null;
	sync_doc: string | null;
	sync_direction: Direction | null;
	sync_status: "Success" | "Failure" | null;
	/** What the API sent (an import) or was sent (an export). */
	object: unknown;
	/** The document as it was saved, or as it was read to export. */
	document: unknown;
	transform: string | null;
	transform_hash: string | null;
	url: string | null;
	request_type: string | null;
	response: string | null;
	diagnostics: unknown;
	traceback: string | null;
}

const TRAIL = "Sync log";

/** `#/logs/<name>`: one log entry, with what was sent, received and found wrong. */
export function Log({ name }: LogProps) {
	const { data: entry, error, isLoading } = useFrappeGetDoc<PullLogDoc>(PULL_LOG, name);
	useSessionRead(entry, error);
	// the status every page shares: asking it again after "Sync now" updates the header too
	const status = useConnectionStatus();
	const actions = useSyncActions(status.mutate);

	const trail: [string, string?][] = [[TRAIL, hrefFor("logs")], [name]];
	if (isLoading) {
		return (
			<>
				<PageHeader breadcrumb={trail} title={name} />
				<SkeletonText paragraph lineCount={6} />
			</>
		);
	}
	if (error || !entry) {
		const missing = readFailure(error).httpStatus === 404;
		return (
			<>
				<PageHeader breadcrumb={trail} title={name} />
				<InlineNotification
					kind="error"
					lowContrast
					hideCloseButton
					title={missing ? `There is no log entry ${name}.` : "The log entry couldn't be loaded."}
					subtitle={
						missing
							? "It may have been cleared: entries are kept for a limited time."
							: getErrorMessage(error, "Reload the page to try again.")
					}
				/>
			</>
		);
	}

	const connection = entry.sync_connection;
	const failed = entry.sync_status === "Failure";
	const diagnostics = readDiagnostics(entry.diagnostics);
	const reason = failed ? lastError(entry.diagnostics) : null;
	const hint = reason ? ERROR_HINTS[reason.code] : undefined;
	const request = entry.url ? `${entry.request_type ?? ""} ${pathOf(entry.url)}`.trim() : null;
	const title = entry.sync_doc
		? `${entry.sync_doctype ?? ""} ${entry.sync_doc}`.trim()
		: (request ?? "Request");
	const row = status.rows.find((found) => found.name === connection);
	const state = row?.state ?? "idle";
	const syncing = state !== "idle" || (connection !== null && actions.busy.has(connection));

	return (
		<>
			<PageHeader
				breadcrumb={trail}
				title={title}
				status={
					failed ? (
						<StatusIndicator kind="failure" label="Failure" />
					) : (
						<StatusIndicator kind="success" label="Success" />
					)
				}
				actions={
					<>
						{entry.sync_doctype && entry.sync_doc && (
							<Button kind="ghost" href={deskFormUrl(entry.sync_doctype, entry.sync_doc)} renderIcon={Launch}>
								Open document
							</Button>
						)}
						{entry.transform && (
							<Button kind="tertiary" href={hrefFor("transforms", entry.transform)}>
								Open transform
							</Button>
						)}
						{failed && connection && (
							<BusyButton
								kind="primary"
								renderIcon={Renew}
								busy={syncing}
								busyText={state === "queued" ? "Queued…" : "Syncing…"}
								// as everywhere: a paused Connection does not sync
								disabled={!row?.enabled}
								onClick={() => void actions.syncNow(connection)}
							>
								Sync connection now
							</BusyButton>
						)}
					</>
				}
			/>
			<Stack gap={6}>
				{failed && (
					<InlineNotification
						kind="error"
						lowContrast
						hideCloseButton
						title={reason ? reason.code : "This entry failed."}
						subtitle={[reason?.message, hint, "The next sync tries this again."].filter(Boolean).join(" ")}
					/>
				)}
				<DescriptionList
					label="Log entry"
					items={[
						[
							"Connection",
							connection ? (
								<Link key="connection" href={hrefFor("connections", connection)}>
									{connection}
								</Link>
							) : (
								"—"
							),
						],
						[
							"Direction",
							entry.sync_direction ? (
								<Tag key="direction" size="sm" type={entry.sync_direction === "Import" ? "cyan" : "purple"}>
									{entry.sync_direction}
								</Tag>
							) : (
								"—"
							),
						],
						["DocType", entry.sync_doctype || "—"],
						[
							"Document",
							entry.sync_doctype && entry.sync_doc ? (
								<Link key="document" href={deskFormUrl(entry.sync_doctype, entry.sync_doc)}>
									{entry.sync_doc}
								</Link>
							) : (
								"—"
							),
						],
						[
							"Transform",
							entry.transform ? (
								<Link key="transform" href={hrefFor("transforms", entry.transform)}>
									{entry.transform}
								</Link>
							) : (
								"—"
							),
						],
						["Transform hash", entry.transform_hash ? <code key="hash">{entry.transform_hash}</code> : "—"],
						[
							"Request",
							entry.url ? (
								<span key="request">
									{entry.request_type && (
										<Tag size="sm" type="gray">
											{entry.request_type}
										</Tag>
									)}{" "}
									<code>{entry.url}</code>
								</span>
							) : (
								"—"
							),
						],
						["Logged", <DateTime key="logged" value={entry.creation} />],
					]}
				/>
				<Tabs>
					<TabList aria-label="What the entry recorded">
						<Tab>{`Diagnostics (${diagnostics.length})`}</Tab>
						<Tab>API object</Tab>
						<Tab>Document</Tab>
						<Tab>Response</Tab>
						<Tab>Traceback</Tab>
					</TabList>
					<TabPanels>
						<TabPanel style={{ paddingInline: 0 }}>
							<LogDiagnostics diagnostics={diagnostics} />
						</TabPanel>
						<TabPanel style={{ paddingInline: 0 }}>
							<JsonBlock value={entry.object} label="API object" emptyText="No API object was recorded." />
						</TabPanel>
						<TabPanel style={{ paddingInline: 0 }}>
							<JsonBlock value={entry.document} label="Document" emptyText="No document was recorded." />
						</TabPanel>
						<TabPanel style={{ paddingInline: 0 }}>
							<JsonBlock value={entry.response} label="Response" emptyText="No response was recorded." />
						</TabPanel>
						<TabPanel style={{ paddingInline: 0 }}>
							<JsonBlock value={entry.traceback} label="Traceback" emptyText="No traceback was recorded." />
						</TabPanel>
					</TabPanels>
				</Tabs>
				<p
					style={{
						color: "var(--cds-text-secondary)",
						fontSize: "var(--cds-helper-text-01-font-size)",
						lineHeight: "var(--cds-helper-text-01-line-height)",
					}}
				>
					Secrets are redacted when the entry is written.
				</p>
			</Stack>
		</>
	);
}
