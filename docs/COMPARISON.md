# Odysseus compared

> A factual product-positioning snapshot, verified on 2026-08-19. Products and
> prices change; follow the linked first-party sources for current details.

## The short answer

**Odysseus itself costs $0.** It is MIT-licensed open-source software. Anyone
can run it on a laptop, workstation, private server, or their own VM/VPS without
creating an Odysseus account or sending the control-plane state to an Odysseus
cloud.

```text
Browser / phone
      │
      │ localhost, SSH tunnel, or private Tailscale URL
      ▼
Odysseus on your laptop, workstation, or VM/VPS
      │
      ├── your Git repositories and worktrees
      ├── your NDJSON history and evidence
      ├── your Codex / Claude / custom agent authentication
      └── optional Docker or devcontainer execution
```

There is no Odysseus license fee, hosted-seat fee, or mandatory hosted control
plane. You still pay for whatever **agent, model API, machine, CI, or cloud
infrastructure** you choose to use. A Codex or Claude subscription does not
become free merely because Odysseus orchestrates it.

## Run it where you choose

One-off on a local machine:

```sh
uvx --from git+https://github.com/jpolec/odysseus odysseus start --open
```

Persistent local installation:

```sh
pipx install git+https://github.com/jpolec/odysseus
odysseus doctor
odysseus start --open
```

Private Linux VM/VPS:

```sh
git clone https://github.com/jpolec/odysseus.git
cd odysseus
sudo scripts/install-vps.sh --service-user "$USER"
```

Reach that private service through an SSH tunnel:

```sh
ssh -N -L 8741:127.0.0.1:8741 USER@VPS
```

Or add `--tailscale` to the VPS installer and open its private tailnet URL from
a laptop, tablet, or phone. A public hostname with TLS and Basic auth is also
supported, but a private tunnel is the safer default.

## These products are not all the same category

- **Odysseus and Cezar** are closest: both are open-source systems that
  orchestrate replaceable coding-agent CLIs around Git worktrees.
- **Factory, Devin, Cursor, and GitHub Copilot** are commercial agent platforms
  with managed services, accounts, usage plans, and much larger hosted or
  enterprise surfaces.
- **dmux, Agetor, and ccmux** focus on local parallel sessions, worktrees,
  terminal navigation, or a kanban-style runtime view.
- **OmniRoute** is primarily an AI model gateway and cost/fallback router. It can
  sit below Odysseus; it does not replace the engineering delivery lifecycle.

Comparing them as if they were identical coding agents would be misleading.

## Deployment and cost

| Product | Product cost | Where execution/control lives | Can you run it on your own ordinary VM? | Mandatory vendor account for the core product? |
| --- | --- | --- | --- | --- |
| **Odysseus** | **Free, MIT** | Your machine; local files and optional containers | **Yes — laptop, workstation, private VM or VPS** | **No** |
| [Cezar](https://github.com/open-mercato/cezar) | Free, MIT | Local machine or VPS | Yes | No |
| [Factory](https://docs.factory.ai/) | Commercial; individual plans start at $20/month | Local, cloud, VM/CI and enterprise deployment patterns | Yes, but the commercial product/account model still applies; airgapped operation is an enterprise deployment | Yes for normal use; enterprise airgapped is a separate model |
| [Devin](https://docs.devin.ai/admin/billing/self-serve) | Limited Free; Pro $20/month; Teams starts at $80/month | Cognition-hosted or customer-dedicated enterprise environments | Not as an independent local control plane; Devin's brain remains in Cognition Cloud | Yes |
| [Cursor](https://cursor.com/pricing) | Limited Hobby; Pro $20/month; Teams $40/user/month | Local IDE for foreground work; cloud agents run in Cursor-managed remote VMs | Not for Cursor cloud/background agents | Yes |
| [GitHub Copilot](https://docs.github.com/en/billing/concepts/product-billing/github-copilot-licenses) | Limited Free; Pro $10/month; Business $19/user/month | GitHub and GitHub Actions for coding-agent work | Self-hosted Actions runners can execute jobs, but Copilot remains a GitHub service | Yes |

The clearest Odysseus promise is therefore not “the only free local tool.” It is:

> **A free, owned delivery system above replaceable coding agents, with no
> mandatory SaaS control plane.**

## Product model

| Dimension | Odysseus | Cezar | Factory | Devin | Cursor cloud agents | GitHub Copilot coding agent |
| --- | --- | --- | --- | --- | --- | --- |
| Primary abstraction | Engineering change and its delivery evidence | Task executed as a configurable workflow | Droid sessions, Missions, and automated SDLC | Managed autonomous agent session | IDE/cloud agent session | GitHub issue/PR agent session |
| Agent independence | Codex, Claude, or custom lanes are replaceable workers | Claude, Codex, OpenCode, and Pi runners | Model-independent within the Droid platform | Devin is the worker | Cursor Agent and supported models | Copilot plus supported partner agents |
| Local-first control state | **Yes: plain local files and NDJSON** | Yes: plain local/repository files | Depends on deployment; enterprise hybrid/airgapped options exist | No: the brain is cloud-hosted | No for cloud-agent state | No |
| Git isolation | Per-task worktrees; optional Docker/devcontainer boundary | Per-task worktrees | Local/cloud execution environments and sandboxes | Dedicated Devbox | Isolated remote Ubuntu VM | GitHub Actions environment |
| Approval-gated dependency graph | **Built in** | Ordered workflows and planning chains | Missions and platform workflows | Planning inside Devin sessions | Planning and parallel agents | Issue/PR-oriented agent workflow |
| Independent checks and evidence | **First-class checks, evaluator, review, CI, Context Receipt, artifact evidence** | Workflow checks and review gate | Strong review, QA, policy, telemetry, and enterprise controls | Tests, review, and managed execution | Agent review, Bugbot, and PR flow | GitHub checks, code scanning, and PR review |
| Accepted vs integrated vs delivered | **Explicit separate lifecycle states** | Review/PR/finish workflow states | Rich SDLC states, depending on configured workflow | PR/session lifecycle | Review and merge lifecycle | PR lifecycle |
| Outcome economics | **Delivery, first-pass rate, cost, failures, and human intervention** | Token/cost visibility and run history | Agent-effectiveness and enterprise analytics | Usage/session analytics | Usage analytics | Organization usage and billing analytics |
| Existing terminal remains first-class | **Yes; tmux discovery and exact-thread handoff are optional** | CLI runners plus web cockpit | Strong CLI/app/web handoff | Web, desktop, CLI, Slack, and API | Primarily Cursor IDE plus web/mobile | GitHub web/CLI workflow |

“Not listed as first-class” does not mean a product can never be extended to do
it. This table describes the public product emphasis, not every possible custom
integration.

## Closest open-source alternatives

### Cezar

[Cezar](https://github.com/open-mercato/cezar) is the closest direct open-source
peer. It is MIT-licensed, runs locally or on a VPS, supports several agent
runners, configurable multi-step workflows, Skills, checks, a web cockpit, and
remote installation. It is a strong choice when the center of the product is:

```text
task → selected workflow → agent/check steps → review/PR
```

Odysseus deliberately centers a wider change record:

```text
requirement → approved DAG → isolated attempts → evidence → decision
            → integration → delivery → measured outcome → future routing
```

The practical Odysseus differentiators are the explicit delivery-state
separation, decision-first Needs You queue, evidence and Context Receipts,
repository memory, accepted-artifact composition, and outcome economics. Cezar
currently has broader public runner coverage and a mature configurable workflow
surface. Neither project should claim that the other is merely a session
launcher.

### dmux, Agetor, and ccmux

- [dmux](https://github.com/standardagents/dmux) is excellent for quickly
  creating many tmux panes backed by Git worktrees, then merging or opening PRs.
- [Agetor](https://github.com/alamops/agetor) provides a local-first kanban and
  structured interaction with parallel CLI agents.
- [ccmux](https://github.com/epilande/ccmux) is a focused tmux monitor and
  navigator that discovers existing sessions and highlights which one needs
  attention.

Choose one of these when the main problem is **launching, seeing, or switching
between sessions**. Choose Odysseus when the main problem is **proving,
governing, integrating, and learning from delivered changes**.

### OmniRoute

[OmniRoute](https://github.com/diegosouzapw/OmniRoute) is also free and
MIT-licensed, but it solves a different layer: routing model requests across
providers, quotas, prices, and fallbacks through a compatible endpoint.

```text
Odysseus:  Which engineering task, worker, policy, evidence, and delivery path?
OmniRoute: Which model/provider should serve this inference request?
```

They can be complementary rather than competitive.

## Where commercial platforms are stronger

Odysseus is not ahead in every dimension.

- **Factory** has a broader enterprise platform: centralized identity and
  policy, OpenTelemetry, managed fleet controls, hybrid and airgapped deployment
  patterns, commercial support, and a polished cross-device product.
- **Devin** offers a highly integrated managed autonomous worker, hosted
  workspace, browser, editor, collaboration, and mature enterprise integrations.
- **Cursor** has exceptional IDE ergonomics, a large integrated user base,
  cloud-agent scale, mobile handoff, and a broad extension/integration surface.
- **GitHub Copilot** is native to the system where many teams already keep
  issues, pull requests, Actions, permissions, and audit logs.

Odysseus trades managed convenience and enterprise breadth for ownership,
inspectability, provider independence, and a zero-license-cost local control
plane.

## Where Odysseus is unusually strong

1. **You own the control plane.** The state, logs, worktrees, evidence, and
   project memory live on infrastructure you choose.
2. **The agent is replaceable.** Codex or Claude is a worker, not the product
   boundary.
3. **Delivery truth is explicit.** Completed, reviewed, accepted, integrated,
   and delivered are not collapsed into one optimistic “done.”
4. **Evidence is durable.** Checks, reviewer output, CI, tool activity, Context
   Receipts, and the exact Git artifact remain inspectable.
5. **The terminal is not taken away.** The web UI manages decisions while tmux
   and direct CLI access remain available.
6. **It measures outcomes.** The portfolio focuses on delivered work, failed
   attempts, cost, retries, and human intervention instead of celebrating token
   volume.
7. **Remote access stays yours.** Run it on a private VPS and reach it through
   an SSH tunnel or Tailscale from a laptop, tablet, or phone.

## Which should you choose?

| If you primarily want… | Start with… |
| --- | --- |
| A free, owned delivery layer above Codex/Claude with evidence and local state | **Odysseus** |
| Open-source, configurable step-by-step agent workflows and broad CLI runner support | Cezar |
| Fast tmux panes and worktrees | dmux |
| A local desktop kanban for parallel CLI agents | Agetor |
| A live tmux session monitor and navigator | ccmux |
| Provider fallback and inference-cost routing | OmniRoute |
| A commercially supported enterprise agent platform | Factory |
| A managed autonomous software engineer | Devin |
| An AI-native editor with cloud agents | Cursor |
| Agent execution centered on GitHub issues, PRs, and Actions | GitHub Copilot |

## Verify the Odysseus claims yourself

```sh
git clone https://github.com/jpolec/odysseus.git
cd odysseus
./install.sh
odysseus doctor
odysseus demo
```

The demo is local and uses disposable state. For the real workflow, authenticate
one supported agent CLI, run `odysseus start --open`, add a Git repository, and
describe one finished change.

For a private VM/VPS, see [Remote and VPS](../README.md#remote-and-vps) and the
[security guide](../SECURITY.md#remote-access). For current product behavior,
see the [version and capabilities record](../VERSION.md).

## First-party sources

- [Odysseus README](../README.md), [MIT license](../LICENSE), and
  [security model](../SECURITY.md)
- [Cezar README](https://github.com/open-mercato/cezar) and
  [MIT license](https://github.com/open-mercato/cezar/blob/main/LICENSE)
- [Factory product documentation](https://docs.factory.ai/),
  [individual pricing](https://docs.factory.ai/pricing/individuals), and
  [deployment patterns](https://docs.factory.ai/enterprise/network-and-deployment)
- [Devin pricing](https://docs.devin.ai/admin/billing/self-serve) and
  [enterprise deployment](https://docs.devin.ai/enterprise/deployment/overview)
- [Cursor pricing](https://cursor.com/pricing),
  [background agents](https://docs.cursor.com/background-agent), and
  [web/mobile agents](https://docs.cursor.com/en/background-agent/web-and-mobile)
- [GitHub Copilot licensing](https://docs.github.com/en/billing/concepts/product-billing/github-copilot-licenses),
  [coding-agent billing](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-copilot/about-billing-for-github-copilot),
  and [third-party coding agents](https://docs.github.com/en/copilot/concepts/agents/about-third-party-coding-agents)
- [dmux](https://github.com/standardagents/dmux),
  [Agetor](https://github.com/alamops/agetor),
  [ccmux](https://github.com/epilande/ccmux), and
  [OmniRoute](https://github.com/diegosouzapw/OmniRoute)
