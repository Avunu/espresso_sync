// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { PageHeader } from "../components/PageHeader";
import { LogsTable } from "./logs/LogsTable";

export interface LogsProps {
	/** The route's query: the log's filters (see LogFilters) and `page`. */
	query: Readonly<Record<string, string>>;
}

const NO_FILTERS = {};

/** `#/logs`: the Sync log, every entry of every Connection. */
export function Logs({ query }: LogsProps) {
	return (
		<>
			<PageHeader
				breadcrumb={[]}
				title="Sync log"
				subtitle="What every sync requested, imported and exported, newest first. A failed entry says why."
			/>
			<LogsTable fixed={NO_FILTERS} showConnection query={query} syncQuery />
		</>
	);
}
