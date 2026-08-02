import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Data table primitives.
 *
 * Wrapped in an overflow container so a wide table scrolls inside itself
 * rather than forcing the whole page to scroll sideways on mobile -- the most
 * common responsive failure in an admin panel.
 */
const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement> & { readonly caption?: string }
>(({ className, caption, children, ...props }, ref) => (
  <div className="relative w-full overflow-x-auto rounded-lg border border-border">
    <table
      ref={ref}
      className={cn("w-full caption-bottom text-sm", className)}
      {...props}
    >
      {caption !== undefined && <caption className="sr-only">{caption}</caption>}
      {children}
    </table>
  </div>
));
Table.displayName = "Table";

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("bg-muted/50 [&_tr]:border-b", className)} {...props} />
));
TableHeader.displayName = "TableHeader";

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("[&_tr:last-child]:border-0", className)} {...props} />
));
TableBody.displayName = "TableBody";

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      // Row highlighting on hover: recommended for data-dense dashboards to
      // keep the eye on one record across many columns.
      "border-b border-border transition-colors hover:bg-muted/40 data-[state=selected]:bg-muted",
      className,
    )}
    {...props}
  />
));
TableRow.displayName = "TableRow";

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    scope="col"
    className={cn(
      "h-11 px-4 text-left align-middle text-xs font-semibold uppercase tracking-wide text-textSecondary",
      className,
    )}
    {...props}
  />
));
TableHead.displayName = "TableHead";

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td ref={ref} className={cn("px-4 py-3 align-middle", className)} {...props} />
));
TableCell.displayName = "TableCell";

/** Consistent empty state so each table does not invent its own. */
function TableEmpty({
  colSpan,
  children,
}: {
  readonly colSpan: number;
  readonly children: React.ReactNode;
}): React.JSX.Element {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} className="py-10 text-center text-textSecondary">
        {children}
      </TableCell>
    </TableRow>
  );
}

export { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableEmpty };
