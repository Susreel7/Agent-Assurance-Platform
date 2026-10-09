/**
 * A short explanation of the product, on the first screen, dismissible.
 *
 * The vocabulary here is unavoidable — accreditation, materiality, evidence chains are
 * what the product sells, and there are no plainer synonyms that stay accurate. What is
 * avoidable is meeting all of it for the first time as navigation labels with no
 * definition anywhere. Four sentences, once, and then it stays dismissed.
 */

import { useState } from "react";

const STORAGE_KEY = "aap.hideIntro";

function initiallyHidden(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function WhatIsThis() {
  const [hidden, setHidden] = useState(initiallyHidden);

  if (hidden) return null;

  function dismiss() {
    try {
      window.localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // Nothing useful to do; it reappears next visit, which is harmless.
    }
    setHidden(true);
  }

  return (
    <section className="rounded-card bg-bg-panel p-5 shadow-card">
      <div className="flex items-start justify-between gap-6">
        <h2 className="text-body font-semibold text-ink-900">What this is</h2>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 text-table text-ink-400 underline underline-offset-2 hover:text-ink-600"
        >
          Hide
        </button>
      </div>

      <div className="mt-2.5 grid max-w-5xl gap-x-8 gap-y-3 text-body text-ink-600 md:grid-cols-2">
        <p>
          You build AI agents — on LangGraph, the Cursor SDK, whatever suits — and run them
          for client companies. Those clients need proof that each agent is safe to use and
          has not quietly changed since they agreed to it. This is where that proof lives.
        </p>
        <p>
          <strong className="font-medium text-ink-900">Runs</strong>, cost and{" "}
          <strong className="font-medium text-ink-900">tools</strong> are the live side: what
          your agents did, what it cost, and which MCP servers they reached for. An MCP
          server your agent calls but never declared is the thing this product is watching
          for.
        </p>
        <p>
          Each new version of an agent is a{" "}
          <strong className="font-medium text-ink-900">change</strong>, and the system
          decides whether it is significant enough that the client has to look again. An{" "}
          <strong className="font-medium text-ink-900">approval</strong> is a client agreeing
          to one specific version — the formal term is an accreditation.
        </p>
        <p>
          <strong className="font-medium text-ink-900">Evidence</strong> is the tamper-proof
          record behind all of it, which a client or an auditor can verify themselves without
          trusting you.
        </p>
      </div>
    </section>
  );
}
