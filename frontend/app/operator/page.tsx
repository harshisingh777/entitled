"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ChevronRight, ClipboardList, Plus } from "lucide-react";
import { Brand } from "@/components/Brand";
import { api, Dashboard, DashboardRow, inr } from "@/lib/api";
import { writePref } from "@/lib/prefs";

const FILTERS: { id: string; label: string; match: (row: DashboardRow) => boolean }[] = [
  { id: "all", label: "All", match: () => true },
  { id: "overdue", label: "Overdue", match: (row) => row.action.overdue },
  { id: "follow_up", label: "Follow-up", match: (row) => row.action.kind === "follow_up" },
  { id: "document", label: "Documents", match: (row) => row.action.kind === "document" },
  { id: "apply", label: "Forms", match: (row) => row.action.kind === "apply" || row.action.kind === "confirm" },
  { id: "interview", label: "Interview", match: (row) => row.action.kind === "interview" },
];

export default function OperatorPage() {
  const router = useRouter();
  const [data, setData] = useState<Dashboard | null>(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState("all");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.dashboard().then(setData).catch(() => setFailed(true));
  }, []);

  const rows = useMemo(() => {
    const match = FILTERS.find((item) => item.id === filter)!.match;
    return (data?.households ?? []).filter(match);
  }, [data, filter]);

  async function addHousehold() {
    setCreating(true);
    try {
      const state = await api.createHousehold({ operator: "Sunita Yadav (ASHA)" });
      writePref("entitled.household", state.household.id);
      router.push(`/h/${state.household.id}`);
    } catch {
      setFailed(true);
      setCreating(false);
    }
  }

  return (
    <div className="operator">
      <header className="home-bar">
        <Brand />
        <div className="app-bar-tools">
          <Link className="btn btn-quiet btn-sm" href="/operator/log"><ClipboardList size={18} aria-hidden="true" /> Action log</Link>
        </div>
      </header>

      <main className="operator-main">
        <div className="operator-head">
          <div>
            <h1>Gram Saathi</h1>
            <p className="muted">Sunita Yadav (ASHA) · each family's details are kept separately</p>
          </div>
          <button type="button" className="btn btn-primary" disabled={creating} onClick={() => void addHousehold()}>
            <Plus size={20} aria-hidden="true" /> New household
          </button>
        </div>

        {failed && <p className="error-text" role="alert">Could not reach the server.</p>}
        {!data && !failed && <p role="status" className="muted">Opening…</p>}

        {data && (
          <>
            <dl className="totals">
              <div><dt>Households</dt><dd>{data.totals.households}</dd></div>
              <div><dt>Pending</dt><dd>{data.totals.pending}</dd></div>
              <div className={data.totals.overdue ? "total-late" : ""}><dt>Overdue</dt><dd>{data.totals.overdue}</dd></div>
              <div><dt>Submitted</dt><dd>{data.totals.submitted}</dd></div>
              <div className="total-wide"><dt>Yearly entitled / receiving</dt><dd>{inr(data.totals.entitled_annual_inr)} <small>/ {inr(data.totals.received_annual_inr)}</small></dd></div>
            </dl>

            <div className="filters" role="group" aria-label="Filter by task">
              {FILTERS.map((item) => (
                <button key={item.id} type="button" className="chip" aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>
                  {item.label} <span className="count">{data.households.filter(item.match).length}</span>
                </button>
              ))}
            </div>

            {rows.length === 0 ? (
              <p className="empty">Nothing in this list right now.</p>
            ) : (
              <div className="house-table" role="table" aria-label="Households and pending tasks">
                <div className="house-row house-row-head" role="row">
                  <span role="columnheader">Household</span>
                  <span role="columnheader">Next task</span>
                  <span role="columnheader">Due</span>
                  <span role="columnheader">Schemes</span>
                  <span role="columnheader">Yearly</span>
                  <span role="columnheader"><span className="sr-only">Open</span></span>
                </div>
                {rows.map((row) => (
                  <Link key={row.id} href={`/h/${row.id}`} className={`house-row ${row.action.overdue ? "house-row-late" : ""}`} role="row">
                    <span role="cell" className="house-name"><strong>{row.name}</strong><small>{row.village}</small></span>
                    <span role="cell" className="house-action">{row.action.en}</span>
                    <span role="cell" className="house-due" data-empty={!row.action.due_at}>
                      {row.action.due_at ? new Date(row.action.due_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—"}
                      {row.action.overdue && <em> late</em>}
                    </span>
                    <span role="cell" className="house-counts">
                      <span>{`${row.eligible} entitled`}</span>
                      {row.near_miss > 0 && <span> · {`${row.near_miss} near`}</span>}
                    </span>
                    <span role="cell" className="house-money">{inr(row.entitled_annual_inr)}</span>
                    <ChevronRight className="house-go" size={20} aria-hidden="true" />
                  </Link>
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
