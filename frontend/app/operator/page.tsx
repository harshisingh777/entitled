"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ChevronRight, ClipboardList, Plus } from "lucide-react";
import { Brand, LangToggle } from "@/components/Brand";
import { api, Dashboard, DashboardRow, inr } from "@/lib/api";
import { useLang, writePref } from "@/lib/lang";

const FILTERS: { id: string; hi: string; en: string; match: (row: DashboardRow) => boolean }[] = [
  { id: "all", hi: "सभी", en: "All", match: () => true },
  { id: "overdue", hi: "देर हो रही", en: "Overdue", match: (row) => row.action.overdue },
  { id: "follow_up", hi: "जाँच", en: "Follow-up", match: (row) => row.action.kind === "follow_up" },
  { id: "document", hi: "दस्तावेज़", en: "Documents", match: (row) => row.action.kind === "document" },
  { id: "apply", hi: "फॉर्म", en: "Forms", match: (row) => row.action.kind === "apply" || row.action.kind === "confirm" },
  { id: "interview", hi: "बातचीत", en: "Interview", match: (row) => row.action.kind === "interview" },
];

export default function OperatorPage() {
  const { t, L } = useLang();
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
          <Link className="btn btn-quiet btn-sm" href="/operator/log"><ClipboardList size={18} aria-hidden="true" /> {t("कार्य लॉग", "Action log")}</Link>
          <LangToggle />
        </div>
      </header>

      <main className="operator-main">
        <div className="operator-head">
          <div>
            <h1>{t("गाँव साथी", "Gram Saathi")}</h1>
            <p className="muted">{t("सुनीता यादव (ASHA) · हर परिवार की जानकारी अलग रखी जाती है", "Sunita Yadav (ASHA) · each family's details are kept separately")}</p>
          </div>
          <button type="button" className="btn btn-primary" disabled={creating} onClick={() => void addHousehold()}>
            <Plus size={20} aria-hidden="true" /> {t("नया परिवार", "New household")}
          </button>
        </div>

        {failed && <p className="error-text" role="alert">{t("सर्वर से जुड़ नहीं पाए।", "Could not reach the server.")}</p>}
        {!data && !failed && <p role="status" className="muted">{t("खुल रहा है…", "Opening…")}</p>}

        {data && (
          <>
            <dl className="totals">
              <div><dt>{t("परिवार", "Households")}</dt><dd>{data.totals.households}</dd></div>
              <div><dt>{t("काम बाकी", "Pending")}</dt><dd>{data.totals.pending}</dd></div>
              <div className={data.totals.overdue ? "total-late" : ""}><dt>{t("देर हो रही", "Overdue")}</dt><dd>{data.totals.overdue}</dd></div>
              <div><dt>{t("आवेदन जमा", "Submitted")}</dt><dd>{data.totals.submitted}</dd></div>
              <div className="total-wide"><dt>{t("सालाना हक़ / मिल रहा", "Yearly entitled / receiving")}</dt><dd>{inr(data.totals.entitled_annual_inr)} <small>/ {inr(data.totals.received_annual_inr)}</small></dd></div>
            </dl>

            <div className="filters" role="group" aria-label={t("काम से छाँटें", "Filter by task")}>
              {FILTERS.map((item) => (
                <button key={item.id} type="button" className="chip" aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>
                  {t(item.hi, item.en)} <span className="count">{data.households.filter(item.match).length}</span>
                </button>
              ))}
            </div>

            {rows.length === 0 ? (
              <p className="empty">{t("इस सूची में अभी कुछ नहीं।", "Nothing in this list right now.")}</p>
            ) : (
              <div className="house-table" role="table" aria-label={t("परिवार और बाकी काम", "Households and pending tasks")}>
                <div className="house-row house-row-head" role="row">
                  <span role="columnheader">{t("परिवार", "Household")}</span>
                  <span role="columnheader">{t("अगला काम", "Next task")}</span>
                  <span role="columnheader">{t("तारीख़", "Due")}</span>
                  <span role="columnheader">{t("योजनाएँ", "Schemes")}</span>
                  <span role="columnheader">{t("सालाना हक़", "Yearly")}</span>
                  <span role="columnheader"><span className="sr-only">{t("खोलें", "Open")}</span></span>
                </div>
                {rows.map((row) => (
                  <Link key={row.id} href={`/h/${row.id}`} className={`house-row ${row.action.overdue ? "house-row-late" : ""}`} role="row">
                    <span role="cell" className="house-name"><strong>{row.name}</strong><small>{row.village}</small></span>
                    <span role="cell" className="house-action">{L(row.action)}</span>
                    <span role="cell" className="house-due" data-empty={!row.action.due_at}>
                      {row.action.due_at ? new Date(row.action.due_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—"}
                      {row.action.overdue && <em> {t("देर", "late")}</em>}
                    </span>
                    <span role="cell" className="house-counts">
                      <span>{t(`${row.eligible} हक़`, `${row.eligible} entitled`)}</span>
                      {row.near_miss > 0 && <span> · {t(`${row.near_miss} क़रीब`, `${row.near_miss} near`)}</span>}
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
