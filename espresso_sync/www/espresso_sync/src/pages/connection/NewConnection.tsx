// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { type RefObject, useEffect, useRef, useState } from "react";
import {
	InlineNotification,
	Modal,
	PasswordInput,
	RadioButton,
	RadioButtonGroup,
	Stack,
	TextInput,
} from "@carbon/react";
import { hostOf } from "../../../../../public/js/portal/connectionForm.ts";
import { type ConnectionDetail, METHODS } from "../../data/api";
import { useToasts } from "../../portal/Toasts";
import { hrefFor } from "../../route";
import { useInlineCall } from "./ShotModal";

type AuthType = "Header-based" | "Basic";

interface NewConnectionProps {
	open: boolean;
	/** What opened the dialog, which gets the focus back. */
	launcherButtonRef: RefObject<HTMLButtonElement | null>;
	onClose: () => void;
}

/**
 * A new Connection: its name, where the API is and how to authenticate. It is made
 * paused and Manual, and its own page opens on it, where the rest is set up. The secret
 * is only ever sent: nothing reads it back.
 */
export function NewConnection({ open, launcherButtonRef, onClose }: NewConnectionProps) {
	const [name, setName] = useState("");
	const [serverUrl, setServerUrl] = useState("");
	const [authType, setAuthType] = useState<AuthType>("Header-based");
	const [apiKey, setApiKey] = useState("");
	const [secret, setSecret] = useState("");
	// the URL is checked once it was left, or Create was tried
	const [urlChecked, setUrlChecked] = useState(false);
	// Through create_connection, which answers as get_connection does. The REST API answers
	// an insert with the document, where the secret is a mask as long as it is.
	const {
		call,
		busy: loading,
		error,
	} = useInlineCall<ConnectionDetail>(METHODS.createConnection, "Try again.");
	const showToast = useToasts();
	const failureRef = useRef<HTMLDivElement>(null);
	// read by onRequestClose: Carbon's Escape handler keeps the one given when the modal opened
	const busy = useRef(false);

	// the Create button had the focus, and is disabled while it runs: the keyboard
	// goes on from the reason it failed
	useEffect(() => {
		if (error) failureRef.current?.focus();
	}, [error]);

	const host = hostOf(serverUrl);
	const basic = authType === "Basic";

	function submit() {
		setUrlChecked(true);
		if (!name.trim() || !host) return;
		busy.current = true;
		// the endpoint makes it paused; a failure is shown below, from the hook's error
		void call({
			values: {
				connection_name: name.trim(),
				server_url: serverUrl.trim(),
				auth_type: authType,
				api_key: apiKey.trim() || null,
				// left out when empty: there is no secret to store
				...(secret ? { api_secret: secret } : {}),
				sync_frequency: "Manual",
			},
		}).then((made) => {
			busy.current = false;
			if (!made) return;
			showToast({
				kind: "success",
				title: `${made.name} was made.`,
				subtitle: "It is paused until you enable it.",
			});
			window.location.hash = hrefFor("connections", made.name);
		});
	}

	return (
		<Modal
			open={open}
			size="md"
			modalHeading="New connection"
			primaryButtonText="Create"
			secondaryButtonText="Cancel"
			primaryButtonDisabled={!name.trim() || !serverUrl.trim()}
			loadingStatus={loading ? "active" : "inactive"}
			loadingDescription="Creating"
			launcherButtonRef={launcherButtonRef}
			preventCloseOnClickOutside
			selectorPrimaryFocus="#connection-name"
			// Carbon disables Cancel while it runs, but not the close button or Escape
			onRequestClose={() => {
				if (!busy.current) onClose();
			}}
			onRequestSubmit={submit}
		>
			<Stack gap={6}>
				<TextInput
					id="connection-name"
					labelText="Name"
					helperText="What the API is called here: no other connection may have it."
					autoComplete="off"
					value={name}
					onChange={(event) => setName(event.target.value)}
				/>
				<TextInput
					id="connection-server-url"
					type="url"
					labelText="Server URL"
					placeholder="https://api.example.com/v1"
					helperText={
						host
							? `Credentials are sent to ${host} only (the Allowed Host).`
							: "The base URL of the API: each transform's path is added to it."
					}
					autoComplete="off"
					spellCheck={false}
					invalid={urlChecked && !host}
					invalidText="Give an http or https URL, such as https://shop.example.com."
					value={serverUrl}
					onChange={(event) => setServerUrl(event.target.value)}
					onBlur={() => setUrlChecked(Boolean(serverUrl.trim()))}
				/>
				<RadioButtonGroup
					legendText="Authentication"
					name="connection-auth-type"
					orientation="vertical"
					valueSelected={authType}
					onChange={(value) => setAuthType(value === "Basic" ? "Basic" : "Header-based")}
				>
					<RadioButton
						id="connection-auth-header"
						value="Header-based"
						labelText="Header-based: a header carries a key or a token"
					/>
					<RadioButton
						id="connection-auth-basic"
						value="Basic"
						labelText="Basic: a username and a password"
					/>
				</RadioButtonGroup>
				<TextInput
					id="connection-api-key"
					labelText={basic ? "Username (optional)" : "Header name (optional)"}
					{...(basic ? {} : { placeholder: "Authorization" })}
					autoComplete="off"
					spellCheck={false}
					value={apiKey}
					onChange={(event) => setApiKey(event.target.value)}
				/>
				<PasswordInput
					id="connection-api-secret"
					labelText={basic ? "Password (optional)" : "Header value (optional)"}
					helperText="Stored encrypted. It can be replaced later, but never read back."
					autoComplete="new-password"
					value={secret}
					onChange={(event) => setSecret(event.target.value)}
				/>
				{error && (
					<div ref={failureRef} tabIndex={-1}>
						<InlineNotification
							kind="error"
							lowContrast
							hideCloseButton
							title="The connection couldn't be created."
							subtitle={error}
						/>
					</div>
				)}
			</Stack>
		</Modal>
	);
}
