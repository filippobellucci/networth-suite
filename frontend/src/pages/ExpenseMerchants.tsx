import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ExpenseCategory, Merchant, MerchantRule, MerchantRuleSaved, MerchantStatus } from "../types";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";
import SegmentedControl from "../components/SegmentedControl";
import { useIsMobile } from "../context/ViewModeContext";
import { formatDate, formatMoneyPrecise } from "../lib/format";
import { errorText } from "../lib/errors";

type Filter = MerchantStatus | "ALL";

// The <select> value meaning "ignore this merchant" -- can't collide with a
// category id, which is always a UUID.
const IGNORE = "__ignore__";

function ruleValue(rule: MerchantRule | null | undefined): string {
  if (!rule) return "";
  return rule.ignored ? IGNORE : rule.category_id ?? "";
}

function appliedMessage(saved: MerchantRuleSaved): string {
  return saved.applied > 0
    ? `Saved — ${saved.applied} transaction${saved.applied === 1 ? "" : "s"} categorized.`
    : "Saved.";
}

/**
 * Counterparty -> category rules. Banks that send no merchant category code
 * (Revolut, through Enable Banking) leave every card payment uncategorized;
 * mapping a merchant here categorizes its past uncategorized transactions
 * right away and every new one as it arrives.
 */
export default function ExpenseMerchants() {
  const isMobile = useIsMobile();
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [rules, setRules] = useState<MerchantRule[]>([]);
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [filter, setFilter] = useState<Filter>("UNMAPPED");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function reload() {
    return Promise.all([api.listMerchants(), api.listMerchantRules(), api.listExpenseCategories()])
      .then(([m, r, c]) => {
        setMerchants(m);
        setRules(r);
        setCategories(c);
      })
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }
  useEffect(() => {
    reload();
  }, []);

  const categoryName = useMemo(() => {
    const byId = new Map(categories.map((c) => [c.id, c]));
    return (id?: string | null) => (id ? byId.get(id)?.name ?? "(deleted category)" : "");
  }, [categories]);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { UNMAPPED: 0, MAPPED: 0, IGNORED: 0, ALL: merchants.length };
    merchants.forEach((m) => (c[m.status] += 1));
    return c;
  }, [merchants]);

  const shown = filter === "ALL" ? merchants : merchants.filter((m) => m.status === filter);
  const containsRules = rules.filter((r) => r.match_type === "CONTAINS");

  async function run(key: string, action: () => Promise<string>) {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      setNotice(await action());
      await reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  /** Saves `value` (a category id, IGNORE, or "" for none) as the rule in `existing`'s place. */
  async function saveRule(
    existing: MerchantRule | null,
    value: string,
    create: { pattern: string; match_type: MerchantRule["match_type"] }
  ): Promise<string> {
    if (value === "") {
      if (!existing) return "Nothing to change.";
      await api.deleteMerchantRule(existing.id);
      return "Rule removed — transactions it already categorized keep their category.";
    }
    const ignored = value === IGNORE;
    if (!existing) {
      return appliedMessage(
        await api.createMerchantRule({ ...create, category_id: ignored ? null : value, ignored })
      );
    }
    if (ignored) return appliedMessage(await api.updateMerchantRule(existing.id, { ignored: true }));
    let recategorize = false;
    if (existing.category_id && existing.category_id !== value) {
      recategorize = confirm(
        `Also move the transactions currently in "${categoryName(existing.category_id)}" to "${categoryName(value)}"?\n\n` +
          "OK moves them; Cancel keeps them where they are and only applies the new category from now on " +
          "(and to ones still uncategorized)."
      );
    }
    return appliedMessage(
      await api.updateMerchantRule(existing.id, { category_id: value, recategorize_previous: recategorize })
    );
  }

  function onMerchantChange(m: Merchant, value: string) {
    // Only an EXACT rule for this very merchant is "its own"; a CONTAINS rule
    // covering it is left alone, and picking something here overrides it.
    const own = m.rule?.match_type === "EXACT" ? m.rule : null;
    run(m.key, () => saveRule(own, value, { pattern: m.name, match_type: "EXACT" }));
  }

  function categoryOptions() {
    return (
      <>
        {categories.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
        <option value={IGNORE}>Ignore (leave uncategorized)</option>
      </>
    );
  }

  if (loading) return <div className="text-muted">Loading…</div>;

  return (
    <div className="space-y-6">
      <p className="text-muted text-sm max-w-2xl">
        Every merchant (or sender, for money coming in) your bank sync has seen. Pick a category once and the
        merchant's past uncategorized transactions are categorized right away, and every new one as it arrives. A
        category you set by hand on a single transaction is never overwritten.
      </p>

      {categories.length === 0 && (
        <div className="card p-4 text-sm text-muted">Create some categories in the Categories tab first.</div>
      )}

      <SegmentedControl
        options={[
          { value: "UNMAPPED", label: `To map (${counts.UNMAPPED})` },
          { value: "MAPPED", label: `Mapped (${counts.MAPPED})` },
          { value: "IGNORED", label: `Ignored (${counts.IGNORED})` },
          { value: "ALL", label: `All (${counts.ALL})` },
        ]}
        value={filter}
        onChange={setFilter}
        className={isMobile ? "w-full" : undefined}
      />

      {notice && <p className="text-gain text-sm">{notice}</p>}
      {error && <p className="text-loss text-sm">{error}</p>}

      {shown.length === 0 ? (
        <div className="card p-6 text-muted text-sm">
          {merchants.length === 0
            ? "No merchants yet — they appear here as bank sync captures transactions."
            : filter === "UNMAPPED"
              ? "Nothing left to map."
              : "None here."}
        </div>
      ) : (
        <ResponsiveTable
          keyFor={(m) => m.key}
          rows={shown}
          columns={
            [
              {
                header: "Merchant",
                cell: (m) => (
                  <span>
                    {m.name}
                    {m.income_count > 0 && (
                      <span className="text-muted text-xs ml-2">{m.expense_count > 0 ? "in & out" : "income"}</span>
                    )}
                  </span>
                ),
              },
              {
                header: "Transactions",
                className: "num",
                cell: (m) => (
                  <span>
                    {m.expense_count + m.income_count}
                    {m.uncategorized_count > 0 && m.status !== "IGNORED" && (
                      <span className="text-muted text-xs ml-1">({m.uncategorized_count} uncategorized)</span>
                    )}
                  </span>
                ),
              },
              {
                header: "Total",
                className: "text-right num",
                headClassName: "text-right",
                cell: (m) => (
                  <span>
                    {m.expense_count > 0 && <span className="text-loss">−{formatMoneyPrecise(m.expense_total)}</span>}
                    {m.expense_count > 0 && m.income_count > 0 && " "}
                    {m.income_count > 0 && <span className="text-gain">+{formatMoneyPrecise(m.income_total)}</span>}
                  </span>
                ),
              },
              {
                header: "Last seen",
                className: "text-muted text-xs whitespace-nowrap",
                cell: (m) => formatDate(m.last_date),
              },
              {
                header: "Category",
                cell: (m) => {
                  const viaContains = m.rule?.match_type === "CONTAINS" ? m.rule : null;
                  return (
                    <select
                      className="input text-xs w-full"
                      disabled={busy === m.key || categories.length === 0}
                      value={viaContains ? "" : ruleValue(m.rule)}
                      onChange={(e) => onMerchantChange(m, e.target.value)}
                    >
                      <option value="">
                        {viaContains
                          ? `${viaContains.ignored ? "Ignored" : categoryName(viaContains.category_id)} (via "${viaContains.pattern}")`
                          : "— to map —"}
                      </option>
                      {categoryOptions()}
                    </select>
                  );
                },
              },
            ] as ResponsiveColumn<Merchant>[]
          }
        />
      )}

      <ContainsRules
        rules={containsRules}
        merchants={merchants}
        categoryName={categoryName}
        categoryOptions={categoryOptions}
        busy={busy}
        disabled={categories.length === 0}
        onSave={(rule, value) => run(rule.id, () => saveRule(rule, value, rule))}
        onCreate={(pattern, value) =>
          run("new-contains", () => saveRule(null, value, { pattern, match_type: "CONTAINS" }))
        }
      />
    </div>
  );
}

function ContainsRules({
  rules,
  merchants,
  categoryName,
  categoryOptions,
  busy,
  disabled,
  onSave,
  onCreate,
}: {
  rules: MerchantRule[];
  merchants: Merchant[];
  categoryName: (id?: string | null) => string;
  categoryOptions: () => React.ReactNode;
  busy: string | null;
  disabled: boolean;
  onSave: (rule: MerchantRule, value: string) => void;
  onCreate: (pattern: string, value: string) => void;
}) {
  const [pattern, setPattern] = useState("");
  const [value, setValue] = useState("");
  const covers = (r: MerchantRule) => merchants.filter((m) => m.rule?.id === r.id).length;

  return (
    <div className="space-y-3">
      <div>
        <h2 className="font-display text-lg">"Contains" rules</h2>
        <p className="text-muted text-sm max-w-2xl">
          For chains with many stores: a piece of the name (e.g. "unicoop") that covers every merchant containing
          it. Used only for merchants without their own category above; the longest matching piece wins.
        </p>
      </div>

      {rules.length > 0 && (
        <ResponsiveTable
          keyFor={(r) => r.id}
          rows={rules}
          columns={
            [
              { header: "Name contains", cell: (r) => <span className="font-mono text-sm">{r.pattern}</span> },
              {
                header: "Covers",
                className: "text-muted text-xs",
                cell: (r) => `${covers(r)} merchant${covers(r) === 1 ? "" : "s"}`,
              },
              {
                header: "Category",
                cell: (r) => (
                  <select
                    className="input text-xs w-full"
                    disabled={busy === r.id || disabled}
                    value={ruleValue(r)}
                    onChange={(e) => onSave(r, e.target.value)}
                    title={r.ignored ? "Ignored" : categoryName(r.category_id)}
                  >
                    {categoryOptions()}
                  </select>
                ),
              },
              {
                header: "",
                noMobileLabel: true,
                className: "text-right",
                cell: (r) => (
                  <button className="text-muted text-xs hover:text-loss" onClick={() => onSave(r, "")}>
                    Delete
                  </button>
                ),
              },
            ] as ResponsiveColumn<MerchantRule>[]
          }
        />
      )}

      <form
        className="card p-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (pattern.trim().length < 3 || !value) return;
          onCreate(pattern.trim(), value);
          setPattern("");
          setValue("");
        }}
      >
        <div className="flex-1 min-w-[10rem]">
          <label className="field-label">Name contains</label>
          <input
            className="input w-full"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="e.g. unicoop (at least 3 characters)"
          />
        </div>
        <div className="flex-1 min-w-[10rem]">
          <label className="field-label">Category</label>
          <select className="input w-full" value={value} onChange={(e) => setValue(e.target.value)} disabled={disabled}>
            <option value="">Pick a category…</option>
            {categoryOptions()}
          </select>
        </div>
        <button
          className="btn-primary"
          disabled={busy === "new-contains" || disabled || pattern.trim().length < 3 || !value}
        >
          Add rule
        </button>
      </form>
    </div>
  );
}
