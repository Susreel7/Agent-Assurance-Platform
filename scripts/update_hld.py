"""Append the modules built since the HLD was last drawn.

The diagram was last saved before the operations, tracing, composition, model-routing and
stress-testing work landed, so it described five fewer modules than exist. It is also the
document the reader uses to check what is missing, which makes a stale copy actively
misleading rather than merely out of date.

Appends rather than rewrites: pages 1-9 are still accurate, and regenerating them would
throw away hand-placed layout for no gain.

    python scripts/update_hld.py            # writes in place
    python scripts/update_hld.py --check    # exit 1 if pages are missing
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HLD = Path(__file__).resolve().parents[2] / "agent-assurance-hld.drawio"

# Matches the existing pages, which is the point — a diagram that looks bolted on does not
# get read. Purple is consumption, blue is platform, green is settled, orange needs
# attention, red is a gap.
PALETTE = {
    "consume": ("#e1d5e7", "#9673a6"),
    "platform": ("#dae8fc", "#6c8ebf"),
    "done": ("#d5e8d4", "#82b366"),
    "partial": ("#ffe6cc", "#d79b00"),
    "gap": ("#f8cecc", "#b85450"),
    "neutral": ("#f5f5f5", "#999999"),
}


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class Page:
    def __init__(self, name: str, page_id: str, title: str, subtitle: str) -> None:
        self.name = name
        self.page_id = page_id
        self.cells: list[str] = []
        self.n = 0
        self.text(title, 60, 30, 1380, 30, size=17, bold=True)
        self.text(subtitle, 60, 62, 1380, 40, size=12, colour="#666666")

    def _id(self) -> str:
        self.n += 1
        return f"{self.page_id}-{self.n}"

    def text(
        self,
        value: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        size: int = 12,
        bold: bool = False,
        colour: str = "#333333",
    ) -> str:
        style = (
            f"text;html=1;align=left;verticalAlign=top;fontSize={size};"
            f"fontStyle={1 if bold else 0};fontColor={colour};"
        )
        return self._cell(esc(value), style, x, y, w, h)

    def box(
        self,
        value: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        tone: str = "platform",
        size: int = 10,
    ) -> str:
        fill, stroke = PALETTE[tone]
        style = (
            f"rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
            f"fontSize={size};align=left;verticalAlign=top;spacingLeft=10;spacingTop=7;"
        )
        return self._cell(esc(value), style, x, y, w, h)

    def band(self, value: str, x: int, y: int, w: int, h: int, *, size: int = 10) -> str:
        style = (
            "rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#b3b3b3;"
            f"dashed=1;fontSize={size};align=left;verticalAlign=top;"
            "spacingLeft=10;spacingTop=6;fontColor=#666666;"
        )
        return self._cell(esc(value), style, x, y, w, h)

    def note(self, value: str, x: int, y: int, w: int, h: int) -> str:
        style = (
            "rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;"
            "fontSize=10;align=left;verticalAlign=top;spacingLeft=10;spacingTop=7;"
        )
        return self._cell(esc(value), style, x, y, w, h)

    def _cell(self, value: str, style: str, x: int, y: int, w: int, h: int) -> str:
        cid = self._id()
        self.cells.append(
            f'        <mxCell id="{cid}" value="{value}" style="{style}" '
            f'vertex="1" parent="1">\n'
            f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />\n'
            f"        </mxCell>"
        )
        return cid

    def arrow(self, src: str, dst: str, label: str = "", *, dashed: bool = False) -> None:
        cid = self._id()
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;"
            f"strokeColor=#666666;fontSize=9;fontColor=#666666;dashed={1 if dashed else 0};"
        )
        self.cells.append(
            f'        <mxCell id="{cid}" value="{esc(label)}" style="{style}" '
            f'edge="1" parent="1" source="{src}" target="{dst}">\n'
            f'          <mxGeometry relative="1" as="geometry" />\n'
            f"        </mxCell>"
        )

    def render(self) -> str:
        body = "\n".join(self.cells)
        return (
            f'  <diagram name="{esc(self.name)}" id="{self.page_id}">\n'
            f'    <mxGraphModel dx="1422" dy="812" grid="1" gridSize="10" guides="1" '
            f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            f'pageWidth="1500" pageHeight="900" math="0" shadow="0">\n'
            f"      <root>\n"
            f'        <mxCell id="{self.page_id}-r0" />\n'
            f'        <mxCell id="1" parent="{self.page_id}-r0" />\n'
            f"{body}\n"
            f"      </root>\n"
            f"    </mxGraphModel>\n"
            f"  </diagram>"
        )


def page_tracing() -> Page:
    p = Page(
        "10. Tracing - Pipeline and Boundary",
        "p10",
        "TRACING — FROM AGENT TO EVIDENCE",
        "What the fleet did. The left half is table stakes against Langfuse and LangSmith. "
        "The right half is the part they do not have, and the reason this module exists at all.",
    )

    p.band("INGEST", 60, 120, 380, 300)
    sdk = p.box(
        "AGENT RUNTIME\nLangGraph, Cursor SDK, CrewAI\n\n"
        "Emits OTLP spans carrying the\nOpenTelemetry GenAI conventions\n(gen_ai.* attributes).",
        80,
        150,
        340,
        110,
        tone="neutral",
    )
    cred = p.box(
        "MACHINE IDENTITY — ABSENT\n\nNo credential exists for an agent,\n"
        "so nothing real can report yet.\nEvery trace in the console is seeded.\n"
        "Blocks tracing, probes and push-to-diff.",
        80,
        275,
        340,
        120,
        tone="gap",
    )
    coll = p.box(
        "COLLECTOR\nOTLP/HTTP on 4318. Buffers to disk,\n"
        "so an API restart does not lose spans.",
        470,
        150,
        300,
        80,
        tone="platform",
    )

    p.band("STORE — append-only, partitioned monthly", 470, 260, 300, 160)
    runs = p.box(
        "agent_runs (0008)\nOne invocation. Cost in integer\nmicros — summing floats over a\n"
        "million rows depends on order.",
        485,
        290,
        270,
        75,
        tone="done",
    )
    steps = p.box(
        "run_steps (0009)\nNode, LLM, tool, MCP, guardrail.\nparent_seq nests; seq is the\n"
        "reporter's counter, not a clock.",
        485,
        375,
        270,
        75,
        tone="done",
    )

    p.band("READ", 800, 120, 300, 300)
    waterfall = p.box("Run waterfall\nNested steps, timing, cost per step.", 815, 150, 270, 55)
    obs = p.box(
        "Observed graph\nTopology derived from steps that\nactually ran — not the descriptor.",
        815,
        215,
        270,
        70,
        tone="done",
    )
    cost = p.box("Cost and tools\nPer agent, per MCP server, per day.", 815, 295, 270, 55)
    sessions = p.box(
        "Sessions — MISSING\nMany runs are one conversation.\nFirst thing a Langfuse user looks for.",
        815,
        360,
        270,
        60,
        tone="gap",
    )

    p.band("WHAT THIS IS FOR — the part Langfuse does not do", 1130, 120, 310, 300)
    recon = p.box(
        "RECONCILIATION\nObserved tools and models against\nwhat the agent declared. A tool\n"
        "nobody declared becomes a finding.",
        1145,
        150,
        280,
        85,
        tone="consume",
    )
    drift = p.box(
        "ROUTING DRIFT\nModels actually called against\nmodels policy allows.",
        1145,
        245,
        280,
        65,
        tone="consume",
    )
    ev = p.box(
        "EVIDENCE\nHashed into the Merkle chain, so a\nclient can verify it without\ntrusting our database.",
        1145,
        320,
        280,
        85,
        tone="consume",
    )

    p.arrow(sdk, coll, "OTLP")
    p.arrow(coll, runs)
    p.arrow(runs, steps)
    p.arrow(steps, waterfall)
    p.arrow(steps, obs)
    p.arrow(runs, cost)
    p.arrow(obs, recon)
    p.arrow(steps, drift)
    p.arrow(recon, ev)
    p.arrow(cred, coll, "blocked", dashed=True)

    p.note(
        "DESIGN DECISION, OPEN — step payloads.\n"
        "There is nowhere to put a prompt, a completion or a tool argument, and every text column is "
        "bounded so they cannot be smuggled in. That was deliberate: the platform holds the exact data "
        "the residency rules on page 12 exist to protect, and holding it weakens the pitch.\n"
        "It is also the main gap against Langfuse — you cannot debug a run you cannot read. "
        "Three options: store nothing (today), store digests plus a redacted preview, or store payloads in "
        "a customer-held bucket with pointers here. The third is most defensible and most work. Needs a decision.",
        60,
        450,
        1380,
        120,
    )

    p.note(
        "BOUNDARY, STATED PLAINLY — Langfuse answers \"what happened\". This module answers "
        "\"was it allowed, and can you prove it to your client\".\n"
        "If tracing is ever positioned as the product, we are selling a cheaper Langfuse and will lose. "
        "Tracing is the data source; assurance is the product.",
        60,
        590,
        1380,
        70,
    )
    return p


def page_review() -> Page:
    p = Page(
        "11. Change Review - Push to Approval",
        "p11",
        "CHANGE REVIEW — A DIFF A NON-TECHNICAL APPROVER CAN SIGN",
        "The differentiator. Nobody else diffs an agent's composition. The premise: people now ship "
        "AI-written code they cannot fully read, so the review has to happen at the level of "
        "capability rather than of source text.",
    )

    push = p.box(
        "1. CODE ARRIVES\nRepository push.\n\nCONNECTION MISSING — today this\n"
        "means running the CLI by hand.",
        60,
        130,
        250,
        105,
        tone="gap",
    )
    extract = p.box(
        "2. EXTRACT\naap extract — static analysis of the\nrepository into a descriptor.\n\n"
        "Tools, rules, skills, sub-agents,\nconfigs, guardrails, model policy.",
        340,
        130,
        250,
        105,
        tone="done",
    )
    comp = p.box(
        "3. COMPOSITION (0010)\nEach element gets a stable identity,\n"
        "so it can be tracked across versions\nrather than diffed as text.\n\n"
        "This is what makes the diff semantic.",
        620,
        130,
        250,
        105,
        tone="done",
    )
    diff = p.box(
        "4. SEMANTIC DIFF\nAdded, removed, changed — per\nelement class, not per line.",
        900,
        130,
        250,
        105,
        tone="done",
    )
    mat = p.box(
        "5. MATERIALITY\nA rule ladder assigns a verdict per\nchange, and records which rung\n"
        "fired so it can be explained.\n\nNo LLM in the verdict path: a\ngenerated verdict is not an\naudit record.",
        1180,
        130,
        260,
        130,
        tone="done",
    )

    brief = p.box(
        "6. REVIEW BRIEF\nDeterministic plain language. \"This agent can now write to the payments "
        "ledger, where before it could only read.\"\nTemplates, not generation — the same change must "
        "always produce the same sentence.",
        340,
        300,
        530,
        100,
        tone="consume",
    )
    gate = p.box(
        "7. CI GATE\nPOST /v1/releases/preview\nBlocks the merge on a material\nchange that has not been approved.",
        900,
        300,
        250,
        100,
        tone="done",
    )
    approve = p.box(
        "8. APPROVE OR REJECT\n/v1/releases/{id}/transition\n\n"
        "THE ENDPOINT EXISTS AND THE\nCONSOLE DOES NOT CALL IT.\n\n"
        "The whole workflow is read-only,\nso every demo ends with \"and then\n"
        "you would approve it\".",
        1180,
        300,
        260,
        130,
        tone="gap",
    )

    p.arrow(push, extract)
    p.arrow(extract, comp)
    p.arrow(comp, diff)
    p.arrow(diff, mat)
    p.arrow(mat, brief)
    p.arrow(brief, gate)
    p.arrow(gate, approve)

    p.box(
        "RECONCILIATION — closes the loop with page 10\n\n"
        "The descriptor says what the agent is supposed to be made of. run_steps says what it actually "
        "called. Comparing the two is where undeclared capability shows up: a tool in use that nobody "
        "declared, an MCP server nobody approved, a model outside policy.\n\n"
        "This is the mechanism behind the product claim that you do not need a strong technical "
        "reviewer — the platform finds the discrepancy, and the reviewer decides what to do about it.",
        60,
        460,
        810,
        140,
        tone="consume",
    )
    p.note(
        "WHY THIS IS THE WEDGE\n\n"
        "Langfuse versions prompts. Portkey versions prompts. Neither versions the agent's tools, "
        "rules, skills, sub-agents or guardrails, because neither models the agent as a durable thing "
        "that outlives a trace.\n\n"
        "Change review and client-facing assurance are the two bundles with no direct competitor. "
        "They should carry the pricing.",
        900,
        460,
        540,
        140,
    )
    return p


def page_routing() -> Page:
    p = Page(
        "12. Model Routing - Where Enforcement Lives",
        "p12",
        "MODEL ROUTING AND DATA RESIDENCY — THE ENFORCEMENT BOUNDARY",
        "The scenario: model selection is set to auto, the router picks a model outside the country, "
        "and the data must not go there. This page is about who stops it.",
    )

    p.band("OUR SIDE — decide and prove", 60, 120, 640, 330)
    cat = p.box(
        "MODEL CATALOGUE (0012)\nProvider, region, and which data\nclasses each model may see.",
        80,
        155,
        290,
        75,
        tone="done",
    )
    resolve = p.box(
        "ALLOWED-MODEL RESOLUTION\nAgent policy plus the engagement's\n"
        "cross-border rules produce the\npermitted set.",
        80,
        245,
        290,
        85,
        tone="done",
    )
    emit = p.box(
        "GATEWAY CONFIG EMISSION\nLiteLLM-compatible. We express the\n"
        "rule in a form something else\nenforces.",
        80,
        345,
        290,
        85,
        tone="done",
    )
    decisions = p.box(
        "POLICY DECISIONS\nRequested region against effective\nregion. When they differ the request\n"
        "was rerouted, and that row is the\nclearest residency artefact we have.",
        400,
        155,
        285,
        100,
        tone="done",
    )
    driftd = p.box(
        "DRIFT DETECTION\nModels observed in run_steps against\nmodels policy allows. Finds a\n"
        "violation after the fact.",
        400,
        270,
        285,
        85,
        tone="partial",
    )
    evid = p.box(
        "EVIDENCE CHAIN\nEvery decision hashed, batched,\npublished.",
        400,
        370,
        285,
        60,
        tone="consume",
    )

    p.band("THE REQUEST PATH — we are not in it", 740, 120, 700, 330)
    gw = p.box(
        "LLM GATEWAY  (LiteLLM, Portkey, Bedrock)\n\n"
        "Sits in the request path. Loads our config.\nThis is the only component that can\n"
        "refuse a call before it leaves.",
        760,
        155,
        330,
        105,
        tone="neutral",
    )
    model = p.box(
        "MODEL PROVIDER\nIn some region, under some\njurisdiction.",
        1120,
        155,
        300,
        105,
        tone="neutral",
    )
    block = p.box(
        "REFERENCE DEPLOYMENT — MISSING\n\n"
        "No running example where a block\nactually happens. LiteLLM in compose,\n"
        "our config loaded, an agent attempting\na disallowed region, the refusal landing\n"
        "as a policy decision and an evidence\nevent.\n\n"
        "Until this exists, residency is a claim.\nHighest-value demo asset in the product.",
        760,
        280,
        330,
        155,
        tone="gap",
    )
    auto = p.box(
        "THE auto CASE — HARDEST OPEN PROBLEM\n\n"
        "With auto selection the SDK chooses at call\ntime, so the allowed set has to be resolved\n"
        "per request rather than per deployment.\n\n"
        "Two ways: the gateway calls us on each\nrequest (adds latency to every call, and makes\n"
        "us a hard dependency), or it evaluates a\nsigned allow-list locally (stale between\n"
        "refreshes). Needs a decision.",
        1120,
        280,
        300,
        155,
        tone="gap",
    )

    p.arrow(cat, resolve)
    p.arrow(resolve, emit)
    p.arrow(emit, gw, "config")
    p.arrow(gw, model, "permitted only")
    p.arrow(gw, decisions, "reports", dashed=True)
    p.arrow(decisions, evid)
    p.arrow(driftd, evid)

    p.note(
        "SAY THIS OUT LOUD IN EVERY DEMO — WE DO NOT BLOCK ANYTHING.\n\n"
        "Enforcement requires being in the request path and we are not there; a gateway is. We are the "
        "policy source and the evidence layer: we decide what is allowed, emit configuration that makes a "
        "gateway enforce it, and hold the proof afterwards.\n\n"
        "That is a defensible position — the gateway is commodity and the policy is not. Claiming to "
        "block traffic ourselves fails the first technical review, and the person asking will be the one "
        "who signs.",
        60,
        480,
        1380,
        120,
    )
    return p


def page_integrity() -> Page:
    p = Page(
        "13. Contract Integrity",
        "p13",
        "CONTRACT INTEGRITY — WHY THE CONSOLE BROKE, AND WHAT NOW PREVENTS IT",
        "Three failures reached the user at once, none of which any test could see. This page exists so "
        "the same class does not return, and because everything on pages 10-12 is only as trustworthy "
        "as this is.",
    )

    p.band("WHAT HAPPENED", 60, 120, 660, 320)
    f1 = p.box(
        "1. A BUNDLE FROM BEFORE THE WORK\n\n"
        "compose built the web image and nginx\nserved the frozen dist. Every other service\n"
        "reloaded from a source mount.\n\n"
        "Four new screens \"did not work\" because\ntheir routes were genuinely not in the\n"
        "bundle being served.",
        80,
        155,
        300,
        140,
        tone="gap",
    )
    f2 = p.box(
        "2. FIFTEEN DEAD URLS\n\n"
        "/v1/findings for /v1/assurance/findings.\n/v1/sla/... for /v1/slos/...\n\n"
        "All fifteen returned 200 in mock mode,\nbecause the mock handlers were written\n"
        "against the same wrong paths.",
        400,
        155,
        300,
        140,
        tone="gap",
    )
    f3 = p.box(
        "3. A DOZEN DRIFTED TYPES\n\n"
        "PolicyVersion declared version, digest,\nsigned_by, signature_status. The API returns\n"
        "semver, rules_digest, published_by — and no\nsignature status at all.\n\n"
        "Those tables rendered blank columns and\nnothing failed, because a hand-written type\n"
        "agrees with itself.",
        80,
        305,
        620,
        125,
        tone="gap",
    )

    p.band("WHAT NOW PREVENTS IT", 760, 120, 680, 320)
    g1 = p.box(
        "compose web target: dev\nVite with a source mount, like every other\nservice. A stale bundle "
        "can no longer be\nserved as if it were current.",
        780,
        155,
        320,
        85,
        tone="done",
    )
    g2 = p.box(
        "npm run client\nopenapi.json to schema.d.ts. Types are\ngenerated, and Wire<\"Name\"> resolves "
        "each\none through it.",
        1120,
        155,
        300,
        85,
        tone="done",
    )
    g3 = p.box(
        "npm run check:api  (in npm run build)\nReads every /v1/ literal out of the source, reads every "
        "route out of the spec, refuses to build on a mismatch. A type checker cannot catch this: a path "
        "is a string, and the two halves live in different languages.",
        780,
        255,
        640,
        85,
        tone="done",
    )
    g4 = p.box(
        "tests/smoke/sweep.py\nCalls all 85 readable routes against a seeded stack and reports the status "
        "codes. Found column c.name does not exist on its first run — raw SQL naming a column that has "
        "been display_name since 0002.",
        780,
        355,
        640,
        85,
        tone="done",
    )

    p.arrow(f1, g1)
    p.arrow(f2, g3)
    p.arrow(f3, g2)

    p.box(
        "THE MOCK LAYER IS GONE — 2,629 LINES DELETED\n\n"
        "src/mocks was a second, independent, hand-written account of a 125-route API, and it disagreed "
        "with the real one in exactly the same places the console did. That is what made the breakage "
        "invisible: the console looked completely healthy in mock mode.\n\n"
        "A fake that agrees with your mistakes is worse than no fake, because it removes the feedback "
        "that would have caught them. The justification for keeping it was frontend work without a "
        "backend, and docker compose up now provides one in a single command.",
        60,
        470,
        680,
        155,
        tone="partial",
    )
    p.note(
        "THE REMAINING HOLE — AND IT IS THE TOP TASK IN tasks.md\n\n"
        "check:api proves the URL exists in openapi.json. Wire<> proves the type matches openapi.json. "
        "Neither proves openapi.json is current.\n\n"
        "openapi.json is a checked-in snapshot. The first backend change that is not followed by "
        "npm run client puts this whole page back to decorative, and the failure mode is the one above: "
        "everything passes, nothing works.\n\n"
        "Fix: CI regenerates the spec from a running API and fails on any diff. Until that exists, treat "
        "the guarantees on this page as conditional.",
        760,
        470,
        680,
        155,
    )

    p.text(
        "Measured after the repair: typecheck clean, lint clean, build passes, 56 of 56 console paths "
        "resolve against 125 routes, 78 of 85 readable routes return 2xx with zero server errors. "
        "The seven that do not are correct refusals — a 409 for an event not yet sealed, 422s for "
        "genuinely required parameters.",
        60,
        645,
        1380,
        50,
        size=11,
        colour="#666666",
    )
    return p


def page_suite() -> Page:
    p = Page(
        "14. Suite Packaging",
        "p14",
        "THE SUITE — FOUR BUNDLES, ONE OBJECT",
        "Sold as a package rather than a product. Each bundle must be separately deployable and "
        "separately licensable, which is a technical constraint on the domain layering, not just a "
        "pricing decision.",
    )

    obs = p.box(
        "OBSERVE\noperations · graph · home\n\n"
        "Tracing, cost, tool and MCP\ninventory, observed topology.\n\n"
        "Competes directly with Langfuse\nand LangSmith. Price it as the way\n"
        "in, not as the margin.",
        60,
        130,
        330,
        175,
        tone="platform",
    )
    ctrl = p.box(
        "CONTROL\npolicy · model_routing · assurance\n\n"
        "Allowed models, residency rules,\nguardrails, probe suites, findings.\n\n"
        "Competes with Portkey and the\ngateway vendors. Differentiated by\n"
        "policy, not by throughput.",
        410,
        130,
        330,
        175,
        tone="platform",
    )
    rev = p.box(
        "REVIEW\ncomposition · materiality · releases\n\n"
        "Semantic diff of an agent's tools,\nrules, skills and sub-agents. A\n"
        "brief a non-technical approver can\nsign. A CI gate that blocks on\nunapproved material change.\n\n"
        "NO DIRECT COMPETITOR.",
        760,
        130,
        330,
        175,
        tone="consume",
    )
    asr = p.box(
        "ASSURE\nevidence · accreditation ·\nattestation · sla · portal\n\n"
        "Merkle-chained evidence, inclusion\nproofs, accreditation lifecycle,\n"
        "service levels and credits, a\nclient-facing trust portal.\n\n"
        "NO DIRECT COMPETITOR.",
        1110,
        130,
        330,
        175,
        tone="consume",
    )

    p.box(
        "SHARED FOUNDATION — registry · customers · engagements · frameworks · bom · evidence primitives\n\n"
        "Every bundle needs the agent and its versions. This is why the suite is worth more than the sum: "
        "the registry is bought once and each bundle makes the others more valuable on the same object.",
        60,
        340,
        1380,
        85,
        tone="done",
    )

    p.box(
        "THE CONSTRAINT THIS PLACES ON THE CODE\n\n"
        "Separate deployability requires the one-way domain dependency rule in AGENTS.md, enforced by "
        "tests/unit/test_domain_layer_order.py. That test caught a real circular import between "
        "composition and assurance.\n\n"
        "It must not be relaxed for convenience: the moment Review imports from Assure, the two cannot "
        "be sold apart, and the packaging above stops being true.",
        60,
        455,
        680,
        150,
        tone="partial",
    )
    p.note(
        "NOT YET TRUE\n\n"
        "No bundle is independently demonstrable. The Overview screen reads from six domains, so the "
        "smallest thing that can be shown today is all of it.\n\n"
        "Needed: per-module licence gating, a deployment profile per bundle, and a landing screen per "
        "bundle that does not reach outside it.",
        760,
        455,
        680,
        150,
    )
    return p


def build() -> str:
    return "\n" + "\n".join(
        page.render()
        for page in (
            page_tracing(),
            page_review(),
            page_routing(),
            page_integrity(),
            page_suite(),
        )
    ) + "\n"


NEW_IDS = ("p10", "p11", "p12", "p13", "p14")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    original = HLD.read_text(encoding="utf-8")
    missing = [pid for pid in NEW_IDS if f'id="{pid}"' not in original]

    if args.check:
        if missing:
            print(f"HLD is missing pages: {', '.join(missing)}")
            return 1
        print("HLD has every expected page.")
        return 0

    if not missing:
        print("Pages already present; nothing to do. Delete them to regenerate.")
        return 0

    if len(missing) != len(NEW_IDS):
        print(
            f"Refusing to run: {', '.join(p for p in NEW_IDS if p not in missing)} already "
            "present. Appending now would duplicate them.",
            file=sys.stderr,
        )
        return 1

    updated = original.replace("</mxfile>", build().lstrip("\n") + "</mxfile>")

    # The attribute said 7 while the file held 9, which is how a reader ends up trusting
    # a count instead of the tab bar.
    page_count = len(re.findall(r"<diagram ", updated))
    updated = re.sub(r'(<mxfile\b[^>]*?)pages="\d+"', rf'\1pages="{page_count}"', updated)

    HLD.write_text(updated, encoding="utf-8")
    print(f"Appended {len(NEW_IDS)} pages. {HLD.name} now has {page_count}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
