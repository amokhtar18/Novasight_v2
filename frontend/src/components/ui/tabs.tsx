import * as React from "react";
import { cn } from "@/lib/cn";
import { focusRing } from "@/components/ui/_shared";

interface TabsContextValue {
  value: string;
  setValue: (v: string) => void;
}
const TabsContext = React.createContext<TabsContextValue | null>(null);

function useTabs(): TabsContextValue {
  const ctx = React.useContext(TabsContext);
  if (!ctx) throw new Error("Tabs components must be used within <Tabs>");
  return ctx;
}

interface TabsProps {
  value: string;
  onValueChange: (v: string) => void;
  children: React.ReactNode;
  className?: string;
}

export function Tabs({ value, onValueChange, children, className }: TabsProps) {
  const ctx = React.useMemo(
    () => ({ value, setValue: onValueChange }),
    [value, onValueChange]
  );
  return (
    <TabsContext.Provider value={ctx}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex h-[var(--control-h-md)] items-center justify-center gap-1 rounded-lg bg-muted/60 p-1 text-muted-foreground",
        className
      )}
      {...props}
    />
  );
}

interface TabsTriggerProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  value: string;
}

export function TabsTrigger({ value, className, ...props }: TabsTriggerProps) {
  const { value: active, setValue } = useTabs();
  const selected = active === value;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      data-state={selected ? "active" : "inactive"}
      onClick={() => setValue(value)}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium transition-all",
        focusRing,
        selected
          ? "bg-card text-foreground shadow-[var(--elevation-1)]"
          : "text-muted-foreground hover:text-foreground",
        className
      )}
      {...props}
    />
  );
}

interface TabsContentProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string;
}

export function TabsContent({ value, className, ...props }: TabsContentProps) {
  const { value: active } = useTabs();
  if (active !== value) return null;
  return (
    <div role="tabpanel" className={cn("animate-in-up", className)} {...props} />
  );
}
