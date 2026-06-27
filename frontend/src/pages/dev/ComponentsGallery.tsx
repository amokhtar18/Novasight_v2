/**
 * Dev-only component gallery — renders every slice-1 primitive across its
 * variants and states (default/hover/focus/invalid/disabled/loading) in the
 * live app theme. Registered only when import.meta.env.DEV (see App.tsx) and
 * lazy-loaded, so it never ships in the production bundle. It is the visual
 * regression surface for the hardened control contract.
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/molecules/Field";

type Size = "sm" | "md" | "lg";
const SIZES: Size[] = ["sm", "md", "lg"];
const BUTTON_VARIANTS = [
  "default",
  "secondary",
  "outline",
  "ghost",
  "destructive",
  "link",
] as const;

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      <Card>
        <CardContent className="flex flex-wrap items-end gap-4 p-6">
          {children}
        </CardContent>
      </Card>
    </section>
  );
}

export function ComponentsGallery() {
  return (
    <div className="mx-auto max-w-5xl space-y-10 py-10">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">
          Component Gallery
        </h1>
        <p className="text-muted-foreground">
          Slice 1 — core control set. Toggle the app theme (Settings) to inspect
          light and dark.
        </p>
      </header>

      <Section title="Button">
        <div className="flex flex-wrap items-center gap-3">
          {BUTTON_VARIANTS.map((variant) => (
            <Button key={variant} variant={variant}>
              {variant}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {SIZES.map((size) => (
            <Button key={size} size={size}>
              size {size}
            </Button>
          ))}
          <Button disabled>disabled</Button>
          <Button loading>loading</Button>
        </div>
      </Section>

      <Section title="Input">
        {SIZES.map((size) => (
          <Input
            key={size}
            size={size}
            aria-label={`input ${size}`}
            placeholder={`size ${size}`}
          />
        ))}
        <Input aria-label="invalid input" invalid placeholder="invalid" />
        <Input aria-label="disabled input" disabled placeholder="disabled" />
      </Section>

      <Section title="Textarea">
        <Textarea aria-label="textarea" placeholder="Type here…" />
        <Textarea aria-label="invalid textarea" invalid placeholder="invalid" />
      </Section>

      <Section title="Select">
        {SIZES.map((size) => (
          <Select key={size} size={size} aria-label={`select ${size}`} defaultValue="a">
            <option value="a">Option A</option>
            <option value="b">Option B</option>
          </Select>
        ))}
        <Select aria-label="invalid select" invalid defaultValue="a">
          <option value="a">Invalid</option>
        </Select>
      </Section>

      <Section title="Card">
        {(["none", "sm", "md", "lg"] as const).map((elevation) => (
          <Card key={elevation} elevation={elevation} className="w-40">
            <CardHeader>
              <CardTitle className="text-base">elevation {elevation}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              Surface
            </CardContent>
          </Card>
        ))}
      </Section>

      <Section title="Field">
        <div className="w-full max-w-sm space-y-4">
          <Field label="Email" hint="We never share it">
            <Input placeholder="you@example.com" />
          </Field>
          <Field label="Name" required error="This field is required">
            <Input defaultValue="" />
          </Field>
          <Field label="Notes">
            <Textarea placeholder="Optional notes" />
          </Field>
        </div>
      </Section>
    </div>
  );
}
