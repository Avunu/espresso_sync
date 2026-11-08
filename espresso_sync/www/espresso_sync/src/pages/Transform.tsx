// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ReactNode } from "react";
import { InlineNotification, Link, SkeletonText, Stack } from "@carbon/react";
import { Launch } from "@carbon/react/icons";
import { useFrappeGetDocList } from "frappe-react-sdk";
import { getErrorMessage } from "../portal/useBackendCall";
import { deskFormUrl, hrefFor } from "../route";
import { useSessionRead } from "../useSessionRead";
import { Details } from "./Details";
import { TRANSFORM } from "./NewTransform";
import { Placeholder } from "./Placeholder";

interface TransformDoc {
	name: string;
	direction: string;
	status: string;
	document_type: string;
	api_spec: string;
	method: string;
	path: string;
}

/** What the transform maps, until the editor that maps it is here. */
function TransformFields({ name }: { name: string }) {
	const { data, error, isLoading } = useFrappeGetDocList<TransformDoc>(TRANSFORM, {
		fields: ["name", "direction", "status", "document_type", "api_spec", "method", "path"],
		filters: [["name", "=", name]],
		limit: 1,
	});
	useSessionRead(data, error);
	const transform = data?.[0];

	if (isLoading) return <SkeletonText paragraph lineCount={4} />;
	if (error || !transform) {
		return (
			<InlineNotification
				kind="error"
				lowContrast
				hideCloseButton
				title={error ? "The transform couldn't be loaded." : `There is no transform ${name}.`}
				subtitle={error ? getErrorMessage(error, "Reload the page to try again.") : ""}
			/>
		);
	}
	const fields: [string, ReactNode][] = [
		["Direction", transform.direction],
		["Status", transform.status],
		["DocType", transform.document_type],
		[
			"API spec",
			<Link key="spec" href={hrefFor("specs", transform.api_spec)}>
				{transform.api_spec}
			</Link>,
		],
		["Operation", <code key="operation">{`${transform.method} ${transform.path}`}</code>],
	];
	return (
		<Stack gap={5}>
			<Details label="About the transform" fields={fields} />
			<div>
				<Link href={deskFormUrl(TRANSFORM, transform.name)} renderIcon={Launch}>
					Open in the desk
				</Link>
			</div>
		</Stack>
	);
}

/** `#/transforms/<name>`: the transform editor's place. */
export function Transform({ name }: { name: string | undefined }) {
	return (
		<Placeholder kind="Transform" name={name}>
			<Stack gap={5}>
				<p>
					The transform editor, which maps an operation&apos;s fields to a DocType&apos;s and back with a
					JSONata expression for each, is on its way.
				</p>
				{name && <TransformFields name={name} />}
			</Stack>
		</Placeholder>
	);
}
