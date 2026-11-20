// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ReactNode } from "react";
import { Breadcrumb, BreadcrumbItem } from "@carbon/react";

interface PageHeaderProps {
	/** The way here, from the page's own section: a label, and for all but the last, its
	 * link. The last is the page itself. A page at the top of its section has no trail. */
	breadcrumb: [label: string, href?: string][];
	title: string;
	/** Beside the title: a StatusIndicator, a Tag. */
	status?: ReactNode;
	subtitle?: ReactNode;
	/** The page's buttons, at the far end of the title's row. */
	actions?: ReactNode;
	/** The page's Tabs, flush with the header's lower edge. */
	children?: ReactNode;
}

/** The top of every page: where it is, what it is (the page's one `h1`), and what can be done. */
export function PageHeader({ breadcrumb, title, status, subtitle, actions, children }: PageHeaderProps) {
	return (
		<header className="es-page-header">
			{/* a trail of one would only repeat the title */}
			{breadcrumb.length > 1 && (
				<Breadcrumb noTrailingSlash aria-label="Breadcrumb">
					{breadcrumb.map(([label, href], index) =>
						index === breadcrumb.length - 1 || !href ? (
							<BreadcrumbItem key={label} isCurrentPage={index === breadcrumb.length - 1}>
								{label}
							</BreadcrumbItem>
						) : (
							<BreadcrumbItem key={label} href={href}>
								{label}
							</BreadcrumbItem>
						),
					)}
				</Breadcrumb>
			)}
			<div className="es-page-header-row">
				<div className="es-page-header-heading">
					<h1 className="es-page-header-title">{title}</h1>
					{status}
				</div>
				{actions && <div className="es-page-header-actions">{actions}</div>}
			</div>
			{subtitle && <div className="es-page-header-subtitle">{subtitle}</div>}
			{children && <div className="es-page-header-tabs">{children}</div>}
		</header>
	);
}
