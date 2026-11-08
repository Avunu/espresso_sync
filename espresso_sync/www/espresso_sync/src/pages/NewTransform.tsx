// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type RefObject, useState } from "react";
import {
	ComboBox,
	InlineNotification,
	Modal,
	RadioButton,
	RadioButtonGroup,
	Stack,
	TextInput,
} from "@carbon/react";
import { useFrappeCreateDoc, useFrappeGetCall } from "frappe-react-sdk";
import { useToasts } from "../portal/Toasts";
import type { FrappeEnvelope } from "../portal/types";
import { getErrorMessage } from "../portal/useBackendCall";
import { hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";

export const TRANSFORM = "Espresso Sync Transform";
/** The methods a transform's Method takes. */
export const TRANSFORM_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

/** One of list_operations' summaries. */
export interface Operation {
	method: string;
	path: string;
	operation_id: string | null;
	summary: string;
	tags: string[];
	deprecated: boolean;
}

type Direction = "Import" | "Export";

interface NewTransformProps {
	open: boolean;
	/** The API Spec's name. */
	spec: string;
	operation: Operation | undefined;
	launcherButtonRef: RefObject<HTMLButtonElement | null>;
	onClose: () => void;
}

/** Whether a DocType's name has the text typed in the combo box in it. */
function hasText({ item, inputValue }: { item: string; inputValue: string | null }): boolean {
	return !inputValue || item.toLowerCase().includes(inputValue.toLowerCase());
}

/**
 * A new Draft transform on an operation: which way it maps, and the DocType on
 * the other side. The editor opens on it once it is made.
 */
export function NewTransform({ open, spec, operation, launcherButtonRef, onClose }: NewTransformProps) {
	const [title, setTitle] = useState(
		operation ? operation.summary || operation.operation_id || `${operation.method} ${operation.path}` : "",
	);
	const [direction, setDirection] = useState<Direction>(operation?.method === "GET" ? "Import" : "Export");
	const [doctype, setDoctype] = useState<string | null>(null);
	const doctypes = useFrappeGetCall<FrappeEnvelope<string[]>>(
		"espresso_sync.api.schema.list_doctypes",
		undefined,
		open ? undefined : null,
	);
	const { createDoc, loading, error, isCompleted } = useFrappeCreateDoc();
	useSessionRead(doctypes.data, doctypes.error);
	useSessionRead(isCompleted, error);
	const showToast = useToasts();

	function submit() {
		if (!operation || !doctype) return;
		createDoc(TRANSFORM, {
			title: title.trim(),
			direction,
			document_type: doctype,
			api_spec: spec,
			method: operation.method,
			path: operation.path,
		}).then(
			(doc) => {
				showToast({ kind: "success", title: `${doc.name} was made as a Draft.` });
				window.location.hash = hrefFor("transforms", doc.name);
			},
			// shown below, from the hook's error
			() => {},
		);
	}

	return (
		<Modal
			open={open}
			size="sm"
			modalHeading="New transform"
			modalLabel={operation && `${operation.method} ${operation.path}`}
			primaryButtonText="Create"
			secondaryButtonText="Cancel"
			primaryButtonDisabled={!title.trim() || !doctype || loading}
			loadingStatus={loading ? "active" : "inactive"}
			loadingDescription="Creating"
			launcherButtonRef={launcherButtonRef}
			preventCloseOnClickOutside
			selectorPrimaryFocus="#transform-title"
			onRequestClose={onClose}
			onRequestSubmit={submit}
		>
			<Stack gap={6}>
				<TextInput
					id="transform-title"
					labelText="Title"
					helperText="The transform's name: no other transform may have it."
					value={title}
					onChange={(event) => setTitle(event.target.value)}
				/>
				<RadioButtonGroup
					legendText="Direction"
					name="transform-direction"
					orientation="vertical"
					valueSelected={direction}
					onChange={(value) => setDirection(value === "Export" ? "Export" : "Import")}
				>
					<RadioButton
						id="transform-import"
						value="Import"
						labelText="Import: the response's objects become documents"
					/>
					<RadioButton
						id="transform-export"
						value="Export"
						labelText="Export: documents are sent as the request body"
					/>
				</RadioButtonGroup>
				<ComboBox
					id="transform-doctype"
					titleText="DocType"
					placeholder="Search the DocTypes"
					helperText="The DocTypes you can read, but child tables and Singles."
					items={doctypes.data?.message ?? []}
					selectedItem={doctype}
					shouldFilterItem={hasText}
					invalid={Boolean(doctypes.error)}
					invalidText={doctypes.error && getErrorMessage(doctypes.error, "The DocTypes couldn't be loaded.")}
					onChange={({ selectedItem }) => setDoctype(selectedItem ?? null)}
				/>
				{error && (
					<InlineNotification
						kind="error"
						lowContrast
						hideCloseButton
						title="The transform couldn't be created."
						subtitle={getErrorMessage(error, "Try again.")}
					/>
				)}
			</Stack>
		</Modal>
	);
}
