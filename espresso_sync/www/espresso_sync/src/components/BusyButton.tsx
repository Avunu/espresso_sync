// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { Button, type ButtonProps, InlineLoading } from "@carbon/react";

type BusyButtonProps = ButtonProps<"button"> & {
	/** Whether the button's call is running. */
	busy: boolean;
	/** What it reads meanwhile: "Saving…". */
	busyText: string;
};

/**
 * A Button that shows, while its call runs, Carbon's InlineLoading in place of its icon
 * and label, as a Modal's primary button does. It stays enabled, so the keyboard stays
 * on it; a press while the call runs is ignored.
 */
export function BusyButton({ busy, busyText, renderIcon, onClick, children, ...rest }: BusyButtonProps) {
	return (
		<Button
			{...rest}
			{...(renderIcon && !busy ? { renderIcon } : {})}
			aria-busy={busy}
			onClick={(event) => {
				if (!busy) onClick?.(event);
			}}
		>
			{busy ? <InlineLoading description={busyText} className="cds--inline-loading--btn" /> : children}
		</Button>
	);
}
