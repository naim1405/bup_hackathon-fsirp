import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  Boxes,
  Fuel,
  GitBranch,
  Radio,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

const nextSteps = [
  {
    icon: Boxes,
    number: "01",
    title: "Network state",
    description:
      "Connect depot, station, route, inventory, arrival, and demand feeds to the operator workspace.",
    tag: "Simulator API",
  },
  {
    icon: Sparkles,
    number: "02",
    title: "Decision intelligence",
    description:
      "Add shortage-risk analysis and explainable, constraint-aware replenishment recommendations.",
    tag: "Forecast + optimize",
  },
  {
    icon: ShieldCheck,
    number: "03",
    title: "Operate resiliently",
    description:
      "Surface health, stale data, disruptions, recovery actions, and measured system performance.",
    tag: "Reliability",
  },
];

export default function Home() {
  return (
    <main className="bg-background text-foreground min-h-screen">
      <header className="bg-card/80 border-b">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8">
          <Link
            href="/"
            className="flex items-center gap-3"
            aria-label="FSIRP home"
          >
            <span className="bg-primary text-primary-foreground flex size-9 items-center justify-center rounded-xl">
              <Fuel className="size-4" aria-hidden="true" />
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-semibold tracking-tight">
                FuelOps
              </span>
              <span className="text-muted-foreground block text-[10px] font-medium tracking-[0.16em] uppercase">
                BUP · FSIRP
              </span>
            </span>
          </Link>

          <div className="flex items-center gap-3">
            <Badge variant="outline" className="gap-1.5 rounded-full px-3 py-1">
              <span className="size-1.5 rounded-full bg-amber-500" />
              Foundation stage
            </Badge>
            <span className="text-muted-foreground hidden text-xs sm:inline">
              Hackathon workspace
            </span>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-5 py-10 sm:px-8 sm:py-14">
        <section className="bg-card relative overflow-hidden rounded-3xl border p-7 shadow-sm sm:p-10 lg:p-12">
          <div className="pointer-events-none absolute -top-28 right-[-4rem] size-80 rounded-full bg-emerald-500/8 blur-3xl" />
          <div className="relative grid gap-10 lg:grid-cols-[1.2fr_0.8fr] lg:items-center">
            <div className="max-w-2xl">
              <Badge
                variant="secondary"
                className="mb-5 gap-1.5 rounded-full px-3 py-1"
              >
                <Activity className="size-3.5" />
                Fuel Supply Intelligence & Resilience
              </Badge>
              <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
                A clearer view of fuel operations starts here.
              </h1>
              <p className="text-muted-foreground mt-5 max-w-xl text-base leading-7 sm:text-lg">
                The Next.js workspace is configured. Simulator data and decision
                workflows are intentionally not connected to the UI yet.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Button asChild size="lg" className="gap-2 rounded-xl">
                  <a
                    href="/api/backend/v1/health"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Check backend health
                    <ArrowUpRight className="size-4" />
                  </a>
                </Button>
                <span className="text-muted-foreground text-xs">
                  Same-origin API proxy is ready for future data calls.
                </span>
              </div>
            </div>

            <Card className="border-border/70 bg-muted/35 relative overflow-hidden rounded-2xl shadow-none">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <CardDescription>Integration status</CardDescription>
                    <CardTitle className="mt-1 text-lg">
                      Ready to connect
                    </CardTitle>
                  </div>
                  <span className="bg-background flex size-10 items-center justify-center rounded-xl border">
                    <Radio className="text-muted-foreground size-4" />
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <Separator className="mb-4" />
                <div className="space-y-3 text-sm">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-muted-foreground">
                      Frontend API path
                    </span>
                    <code className="bg-background rounded-md px-2 py-1 text-xs">
                      /api/backend/*
                    </code>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-muted-foreground">
                      Backend target
                    </span>
                    <code className="bg-background rounded-md px-2 py-1 text-xs">
                      server-side env
                    </code>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-muted-foreground">
                      Live simulator data
                    </span>
                    <Badge
                      variant="outline"
                      className="rounded-full font-normal"
                    >
                      Not wired yet
                    </Badge>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </section>

        <section className="mt-12">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-muted-foreground text-xs font-semibold tracking-[0.14em] uppercase">
                Build plan
              </p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight">
                Foundation for the operations console
              </h2>
            </div>
            <div className="text-muted-foreground inline-flex items-center gap-2 text-xs">
              <GitBranch className="size-3.5" />
              Frontend scaffold
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {nextSteps.map((step) => {
              const Icon = step.icon;
              return (
                <Card key={step.number} className="rounded-2xl shadow-none">
                  <CardHeader>
                    <div className="mb-3 flex items-center justify-between">
                      <span className="bg-muted flex size-10 items-center justify-center rounded-xl">
                        <Icon className="size-4" />
                      </span>
                      <span className="text-muted-foreground font-mono text-xs">
                        {step.number}
                      </span>
                    </div>
                    <CardTitle>{step.title}</CardTitle>
                    <CardDescription className="min-h-12 leading-6">
                      {step.description}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Badge
                      variant="secondary"
                      className="rounded-full font-normal"
                    >
                      {step.tag}
                    </Badge>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </section>

        <footer className="text-muted-foreground mt-12 flex flex-col justify-between gap-2 border-t pt-5 text-xs sm:flex-row">
          <span>
            BUP CSE Fest · Fuel Supply Intelligence & Resilience Platform
          </span>
          <span>Next.js · TypeScript · Tailwind CSS · shadcn/ui</span>
        </footer>
      </div>
    </main>
  );
}
