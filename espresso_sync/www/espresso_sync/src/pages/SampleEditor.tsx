// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { useState } from "react";
import { Button, InlineNotification, Stack, TextArea } from "@carbon/react";
import { ChevronLeft, ChevronRight, Download, TrashCan } from "@carbon/react/icons";
import { useBackendCall } from "../portal/useBackendCall";

/** fetch_sample's page size: what the server returns by default. */
const PAGE = 20;

interface SampleEditorProps {
	transform: string;
	importing: boolean;
	text: string;
	/** Why the text isn't a sample, if it isn't. */
	error: string | undefined;
	items: number;
	/** A whole number past ±2^53 was in it: JSON reading has already rounded it. */
	unsafe: boolean;
	onChange: (text: string) => void;
}

/**
 * The source items the transform is previewed and checked on: pasted, or
 * fetched a page at a time with fetch_sample (from the operation for an
 * import, from the DocType's documents for an export). Saved with the rules.
 */
export function SampleEditor({
	transform,
	importing,
	text,
	error,
	items,
	unsafe,
	onChange,
}: SampleEditorProps) {
	const [start, setStart] = useState<number | undefined>();
	const [more, setMore] = useState(false);
	const fetchSample = useBackendCall<{ items: unknown[]; more: boolean }>(
		"espresso_sync.api.transform.fetch_sample",
		"The sample couldn't be fetched.",
	);

	async function fetchFrom(from: number) {
		const result = await fetchSample.call({ name: transform, start: from, limit: PAGE });
		if (!result.ok) return;
		setStart(from);
		setMore(result.data.more);
		onChange(JSON.stringify(result.data.items, null, 2));
	}

	const source = importing
		? "the operation's response, from the Connection's server, after the saved Items Pointer"
		: "the DocType's documents, newest first";
	return (
		<Stack gap={5}>
			<TextArea
				id="transform-sample"
				labelText="Sample items (JSON)"
				helperText={`A list of source items, or one. Paste them, or fetch ${source}. ${items} ${items === 1 ? "item" : "items"}.`}
				rows={12}
				spellCheck={false}
				value={text}
				invalid={error !== undefined}
				invalidText={error && `${error}: the preview shows the last sample that was JSON.`}
				style={{ fontFamily: "var(--cds-code-01-font-family)" }}
				onChange={(event) => onChange(event.target.value)}
			/>
			{unsafe && (
				<InlineNotification
					kind="warning"
					lowContrast
					hideCloseButton
					title="A number in the sample is too big to read exactly."
					subtitle="Whole numbers past 9007199254740991 are rounded in the browser: the preview, and a sample fetched here, may show them changed. A pasted sample is saved as written, and the server reads it exactly."
				/>
			)}
			<div>
				<Button
					kind="tertiary"
					size="md"
					renderIcon={Download}
					disabled={fetchSample.loading}
					onClick={() => void fetchFrom(0)}
				>
					{start === undefined ? "Fetch a sample" : "Fetch again"}
				</Button>
				<Button
					kind="ghost"
					size="md"
					renderIcon={ChevronLeft}
					disabled={fetchSample.loading || !start}
					onClick={() => void fetchFrom(Math.max(0, (start ?? 0) - PAGE))}
				>
					Previous {PAGE}
				</Button>
				<Button
					kind="ghost"
					size="md"
					renderIcon={ChevronRight}
					disabled={fetchSample.loading || start === undefined || !more}
					onClick={() => void fetchFrom((start ?? 0) + PAGE)}
				>
					Next {PAGE}
				</Button>
				<Button kind="ghost" size="md" renderIcon={TrashCan} disabled={!text} onClick={() => onChange("")}>
					Clear the sample
				</Button>
			</div>
		</Stack>
	);
}
