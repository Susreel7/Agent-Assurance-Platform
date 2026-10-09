import clsx from "clsx";

type ToolbarProps = {
  children: React.ReactNode;
  className?: string;
};

export function Toolbar({ children, className }: ToolbarProps) {
  return (
    <div className={clsx("flex flex-wrap items-center gap-2", className)} role="toolbar">
      {children}
    </div>
  );
}
