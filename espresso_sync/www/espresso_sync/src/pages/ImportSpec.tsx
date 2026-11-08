// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type RefObject, useEffect, useRef, useState } from "react";
import {
	FileUploader,
	InlineNotification,
	Modal,
	Select,
	SelectItem,
	Stack,
	Tab,
	TabList,
	TabPanel,
	TabPanels,
	Tabs,
	TextArea,
	TextInput,
} from "@carbon/react";
import { useFrappeGetDocList, useFrappePostCall } from "frappe-react-sdk";
import type { FrappeResponse } from "frappe-types";
import { MAX_SOURCE_BYTES, prepareSpec, SpecImportError } from "../../../../public/js/editor/specImport.ts";
import { getErrorMessage } from "../portal/useBackendCall";
import { useSessionRead } from "../useSessionRead";

const CONNECTION = "Espresso Sync Connection";
const SOURCES = ["URL", "File", "Paste"] as const;
const MAX_SOURCE_MB = MAX_SOURCE_BYTES / (1024 * 1024);

/** What save_spec answers. */
export interface SavedSpec {
	name: string;
	spec_hash: string;
	changed: boolean;
	operations: unknown[];
}

/** The API Spec a re-import replaces the spec of. */
export interface ReimportedSpec {
	name: string;
	title: string;
	connection: string | null;
	source_url: string | null;
}

interface SourceText {
	url: string;
	text: string;
}

interface ImportFailure {
	title: string;
	details: string[];
}

/** Why the import failed: specImport's reasons, or save_spec's, one to a line. */
function toFailure(error: unknown): ImportFailure {
	if (error instanceof SpecImportError) return { title: error.message, details: error.details };
	const [title = "", ...details] = (
		error instanceof Error ? error.message : getErrorMessage(error, "The spec couldn't be saved.")
	).split("\n");
	return { title, details };
}

interface ImportSpecProps {
	open: boolean;
	/** Re-import this API Spec; without it, the import makes a new one. */
	spec?: ReimportedSpec;
	launcherButtonRef: RefObject<HTMLButtonElement | null>;
	onClose: () => void;
	onImported: (saved: SavedSpec) => void;
}

/**
 * Import an API's OpenAPI description from a URL, a file or pasted text. The text
 * is bundled and upgraded in the browser (specImport.ts), with every URL
 * fetched by the server's fetch_spec_source, then checked and stored by save_spec.
 */
export function ImportSpec({ open, spec, launcherButtonRef, onClose, onImported }: ImportSpecProps) {
	const [source, setSource] = useState(spec?.source_url || !spec ? 0 : 2);
	const [url, setUrl] = useState(spec?.source_url ?? "");
	const [file, setFile] = useState<File | undefined>();
	const [text, setText] = useState("");
	const [connection, setConnection] = useState("");
	const [title, setTitle] = useState("");
	const [stage, setStage] = useState<string | undefined>();
	const [failure, setFailure] = useState<ImportFailure | undefined>();
	const failureRef = useRef<HTMLDivElement>(null);
	// read by onRequestClose: Carbon's Escape handler keeps the one given when the modal opened
	const busy = useRef(false);

	const { data: connections } = useFrappeGetDocList<{ name: string }>(
		CONNECTION,
		{ fields: ["name"], orderBy: { field: "name", order: "asc" }, limit: 500 },
		spec ? null : undefined,
	);
	const fetchSource = useFrappePostCall<FrappeResponse<SourceText>>(
		"espresso_sync.api.schema.fetch_spec_source",
	);
	const saveSpec = useFrappePostCall<FrappeResponse<SavedSpec>>("espresso_sync.api.schema.save_spec");
	useSessionRead(fetchSource.result, fetchSource.error);
	useSessionRead(saveSpec.result, saveSpec.error);

	// the primary button had the focus, and is disabled while the import runs: the
	// keyboard goes on from the reason it failed
	useEffect(() => {
		if (failure) failureRef.current?.focus();
	}, [failure]);

	// a re-import fetches with the credentials of the Connection the spec belongs to
	const credentials = (spec ? spec.connection : connection) || undefined;
	const ready = [url.trim(), file, text.trim()][source];

	/** The text at a URL, fetched by the server; a failure is an Error with its reason. */
	async function fetchText(target: string): Promise<SourceText> {
		try {
			const { message } = await fetchSource.call({ url: target, connection: credentials });
			if (message) return message;
		} catch (error) {
			throw new Error(getErrorMessage(error, `${target} couldn't be fetched.`), { cause: error });
		}
		// frappe leaves `message` out only when the method returned None
		throw new Error(`${target} couldn't be fetched.`);
	}

	async function submit() {
		setFailure(undefined);
		busy.current = true;
		try {
			let sourceText: string;
			let origin: string | undefined;
			if (source === 0) {
				setStage("Fetching the spec");
				const fetched = await fetchText(url.trim());
				sourceText = fetched.text;
				// relative references are read against where the spec was found
				origin = fetched.url;
			} else if (source === 1 && file) {
				if (file.size > MAX_SOURCE_BYTES) throw new Error(`The file is larger than ${MAX_SOURCE_MB} MB.`);
				setStage("Reading the file");
				sourceText = await file.text();
			} else {
				sourceText = text;
			}
			setStage("Bundling and upgrading");
			const prepared = await prepareSpec(sourceText, {
				...(origin === undefined ? {} : { origin }),
				fetchText: async (ref) => (await fetchText(ref)).text,
			});
			const specTitle = spec?.title ?? (title.trim() || prepared.title);
			if (!specTitle) throw new Error("Give the spec a title: it has none of its own.");
			setStage("Saving");
			const { message: saved } = await saveSpec.call({
				spec_json: prepared.specJson,
				title: specTitle,
				connection: spec ? undefined : credentials,
				// as typed: a re-import fetches it again, wherever it redirects to then
				source_url: source === 0 ? url.trim() : undefined,
				source_format: prepared.sourceFormat,
				original_version: prepared.originalVersion,
				name: spec?.name,
			});
			if (!saved) throw new Error("The spec couldn't be saved.");
			onImported(saved);
		} catch (error) {
			setFailure(toFailure(error));
		} finally {
			busy.current = false;
			setStage(undefined);
		}
	}

	return (
		<Modal
			open={open}
			size="md"
			modalHeading={spec ? `Re-import ${spec.title}` : "Import an API spec"}
			primaryButtonText={spec ? "Re-import" : "Import"}
			secondaryButtonText="Cancel"
			primaryButtonDisabled={!ready}
			loadingStatus={stage === undefined ? "inactive" : "active"}
			loadingDescription={stage ?? ""}
			launcherButtonRef={launcherButtonRef}
			preventCloseOnClickOutside
			hasScrollingContent
			// the chosen source's tab, from which the keyboard goes on into its panel
			selectorPrimaryFocus='[role="tab"][aria-selected="true"]'
			// Carbon disables Cancel while the import runs, but not the close button or Escape
			onRequestClose={() => {
				if (!busy.current) onClose();
			}}
			onRequestSubmit={() => void submit()}
		>
			<Stack gap={6}>
				<p>
					An OpenAPI description in JSON or YAML. Swagger 2.0 and OpenAPI 3.0 are upgraded to OpenAPI 3.1, and
					the files it refers to are fetched and bundled in.
				</p>
				{failure && (
					<div ref={failureRef} tabIndex={-1}>
						<InlineNotification kind="error" lowContrast hideCloseButton title={failure.title}>
							{failure.details.length > 0 && (
								<ul>
									{failure.details.map((detail) => (
										<li key={detail}>{detail}</li>
									))}
								</ul>
							)}
						</InlineNotification>
					</div>
				)}
				<Tabs
					selectedIndex={source}
					onChange={({ selectedIndex }) => {
						setSource(selectedIndex);
						setFailure(undefined);
					}}
				>
					<TabList aria-label="Where the spec comes from">
						{SOURCES.map((label) => (
							<Tab key={label}>{label}</Tab>
						))}
					</TabList>
					<TabPanels>
						<TabPanel>
							<TextInput
								id="spec-url"
								type="url"
								labelText="URL"
								placeholder="https://api.example.com/openapi.json"
								helperText="Fetched by the server, as are the files it refers to."
								value={url}
								onChange={(event) => setUrl(event.target.value)}
							/>
						</TabPanel>
						<TabPanel>
							<FileUploader
								labelTitle="File"
								labelDescription={`JSON or YAML, at most ${MAX_SOURCE_MB} MB. Files it refers to by a relative path can't be found: import it from its URL instead.`}
								buttonLabel="Choose a file"
								buttonKind="tertiary"
								accept={[".json", ".yaml", ".yml"]}
								filenameStatus="edit"
								iconDescription="Remove the file"
								onChange={(event) => setFile((event.target as HTMLInputElement).files?.[0] ?? undefined)}
								onDelete={() => setFile(undefined)}
							/>
						</TabPanel>
						<TabPanel>
							<TextArea
								id="spec-text"
								labelText="Spec"
								rows={10}
								value={text}
								onChange={(event) => setText(event.target.value)}
							/>
						</TabPanel>
					</TabPanels>
				</Tabs>
				{!spec && (
					<Select
						id="spec-connection"
						labelText="Connection (optional)"
						helperText="The spec is named after it, and a URL on its Allowed Host is fetched with its credentials."
						value={connection}
						onChange={(event) => setConnection(event.target.value)}
					>
						<SelectItem value="" text="None" />
						{(connections ?? []).map(({ name }) => (
							<SelectItem key={name} value={name} text={name} />
						))}
					</Select>
				)}
				{!spec && (
					<TextInput
						id="spec-title"
						labelText="Title (optional)"
						helperText="Leave it empty to use the spec's own title."
						value={title}
						onChange={(event) => setTitle(event.target.value)}
					/>
				)}
			</Stack>
		</Modal>
	);
}
