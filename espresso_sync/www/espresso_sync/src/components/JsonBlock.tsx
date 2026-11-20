// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Button, CodeSnippet, Stack } from "@carbon/react";
import { Download } from "@carbon/react/icons";
import { prettyJson } from "../../../../public/js/portal/logs.ts";

/** Above this many characters only the start is shown: a longer one stalls the page. */
const MAX_SHOWN = 200 * 1024;

interface JsonBlockProps {
	/** A value, or JSON text as a log entry stores it. */
	value: unknown;
	/** What the value is: "API object". Names the block and the downloaded file. */
	label: string;
	/** What to say when there is no value. */
	emptyText?: string;
}

/** Hand `text` to the browser as a file. */
function download(text: string, label: string): void {
	const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
	const link = document.createElement("a");
	link.href = url;
	link.download = `${label.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.json`;
	link.click();
	URL.revokeObjectURL(url);
}

/** A JSON value laid out to read and to copy. A very long one is cut short, with the
 * whole of it as a download. */
export function JsonBlock({ value, label, emptyText = "Nothing was recorded." }: JsonBlockProps) {
	const text = prettyJson(value);
	if (!text) return <p style={{ color: "var(--cds-text-secondary)" }}>{emptyText}</p>;
	const cut = text.length > MAX_SHOWN;
	return (
		<Stack gap={3}>
			<CodeSnippet
				type="multi"
				aria-label={label}
				feedback="Copied"
				copyButtonDescription="Copy"
				maxCollapsedNumberOfRows={15}
			>
				{cut ? text.slice(0, MAX_SHOWN) : text}
			</CodeSnippet>
			{cut && (
				<div style={{ display: "flex", alignItems: "center", gap: "var(--cds-spacing-05)" }}>
					<span style={{ color: "var(--cds-text-secondary)" }}>Only the start is shown.</span>
					<Button kind="ghost" size="sm" renderIcon={Download} onClick={() => download(text, label)}>
						Download all of it
					</Button>
				</div>
			)}
		</Stack>
	);
}
