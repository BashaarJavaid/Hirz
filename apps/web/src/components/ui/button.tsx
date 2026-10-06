import type { ComponentProps } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

const variants = cva("inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50 min-h-12 px-4 py-2", {
  variants: { variant: { default: "bg-[var(--accent)] text-white hover:opacity-90", outline: "border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--muted)]" } },
  defaultVariants: { variant: "outline" },
});
export function Button({ className, variant, asChild = false, ...props }: ComponentProps<"button"> & VariantProps<typeof variants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={twMerge(clsx(variants({ variant }), className))} {...props} />;
}
