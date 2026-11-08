// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type RefObject, useState } from "react";
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
import { MAX_SOURCE_BYTES, prepareSpec, SpecImportError } from "../../../../public/js/editor/specImport.ts";
import { useSession } from "../portal/session";
import type { FrappeEnvelope } from "../portal/types";
import { getErrorMessage, readFailure } from "../portal/useBackendCall";

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

/**
 * A whitelisted method whose failure is shown in the form rather than as a toast:
 * it throws an Error with the server's message. A 403 ends the session, as anywhere.
 */
function useFormCall<T>(method: string, fallback: string) {
	const { call } = useFrappePostCall<FrappeEnvelope<T>>(method);
	const { recordActivity, reportForbidden } = useSession();
	return async (params: Record<string, unknown>): Promise<T> => {
		try {
			const { message } = await call(params);
			recordActivity();
			return message;
		} catch (error) {
			if (readFailure(error).httpStatus === 403) reportForbidden();
			throw new Error(getErrorMessage(error, fallback), { cause: error });
		}
	};
}

function toFailure(error: unknown): ImportFailure {
	if (error instanceof SpecImportError) return { title: error.message, details: error.details };
	return { title: error instanceof Error ? error.message : String(error), details: [] };
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
 * is bundled, upgraded and checked in the browser (specImport.ts), with every
 * URL fetched by the server's fetch_spec_source, then stored with save_spec.
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

	const { data: connections } = useFrappeGetDocList<{ name: string }>(
		CONNECTION,
		{ fields: ["name"], orderBy: { field: "name", order: "asc" }, limit: 500 },
		spec ? null : undefined,
	);
	const fetchSource = useFormCall<SourceText>(
		"espresso_sync.api.schema.fetch_spec_source",
		"The URL couldn't be fetched.",
	);
	const saveSpec = useFormCall<SavedSpec>(
		"espresso_sync.api.schema.save_spec",
		"The spec couldn't be saved.",
	);

	// a re-import fetches with the credentials of the Connection the spec belongs to
	const credentials = (spec ? spec.connection : connection) || undefined;
	const ready = [url.trim(), file, text.trim()][source];

	async function submit() {
		setFailure(undefined);
		try {
			let sourceText: string;
			let origin: string | undefined;
			if (source === 0) {
				setStage("Fetching the spec");
				const fetched = await fetchSource({ url: url.trim(), connection: credentials });
				sourceText = fetched.text;
				origin = fetched.url;
			} else if (source === 1 && file) {
				if (file.size > MAX_SOURCE_BYTES) throw new Error(`The file is larger than ${MAX_SOURCE_MB} MB.`);
				sourceText = await file.text();
			} else {
				sourceText = text;
			}
			setStage("Bundling, upgrading and checking");
			const prepared = await prepareSpec(sourceText, {
				...(origin === undefined ? {} : { origin }),
				fetchText: async (ref) => (await fetchSource({ url: ref, connection: credentials })).text,
			});
			const specTitle = spec?.title ?? (title.trim() || prepared.title);
			if (!specTitle) throw new Error("Give the spec a title: it has none of its own.");
			setStage("Saving");
			const saved = await saveSpec({
				spec_json: prepared.specJson,
				title: specTitle,
				connection: spec ? undefined : credentials,
				source_url: origin,
				source_format: prepared.sourceFormat,
				original_version: prepared.originalVersion,
				name: spec?.name,
			});
			onImported(saved);
		} catch (error) {
			setFailure(toFailure(error));
		} finally {
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
			primaryButtonDisabled={!ready || stage !== undefined}
			loadingStatus={stage === undefined ? "inactive" : "active"}
			loadingDescription={stage ?? ""}
			launcherButtonRef={launcherButtonRef}
			preventCloseOnClickOutside
			hasScrollingContent
			// the chosen source's tab, from which the keyboard goes on into its panel
			selectorPrimaryFocus='[role="tab"][aria-selected="true"]'
			onRequestClose={onClose}
			onRequestSubmit={() => void submit()}
		>
			<Stack gap={6}>
				<p>
					An OpenAPI description in JSON or YAML. Swagger 2.0 and OpenAPI 3.0 are upgraded to OpenAPI 3.1, and
					the files it refers to are fetched and bundled in.
				</p>
				{failure && (
					<InlineNotification kind="error" lowContrast hideCloseButton title={failure.title}>
						{failure.details.length > 0 && (
							<ul>
								{failure.details.map((detail) => (
									<li key={detail}>{detail}</li>
								))}
							</ul>
						)}
					</InlineNotification>
				)}
				<Tabs selectedIndex={source} onChange={({ selectedIndex }) => setSource(selectedIndex)}>
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
