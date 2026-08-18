#!/usr/bin/env node
/** Capture a deterministic Odysseus walkthrough through the Chrome DevTools Protocol. */

import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";

function argumentsMap(values) {
  const result = {};
  for (let index = 2; index < values.length; index += 2) {
    result[values[index].replace(/^--/, "")] = values[index + 1];
  }
  return result;
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

class CDPClient {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 1;
    this.pending = new Map();
    this.ready = new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result || {});
    });
  }

  async send(method, params = {}, sessionId = undefined) {
    await this.ready;
    const id = this.nextId++;
    const message = { id, method, params };
    if (sessionId) message.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify(message));
    });
  }

  close() {
    this.socket.close();
  }
}

const args = argumentsMap(process.argv);
const required = ["base-url", "project-id", "review-run-id", "accepted-run-id", "frames-dir", "chrome"];
for (const key of required) {
  if (!args[key]) throw new Error(`missing --${key}`);
}

const fps = Math.max(1, Number(args.fps || 10));
const durationScale = Math.max(0.01, Number(args["duration-scale"] || 1));
const width = 1440;
const height = 900;
const baseUrl = args["base-url"].replace(/\/$/, "");
const scenes = [
  {
    seconds: 9,
    url: `${baseUrl}/?view=work`,
    expect: "Repositories",
    eyebrow: "01  WORKSPACE",
    title: "One place for every repository",
    body: "See active work, decisions, and delivery state across projects.",
    from: [1110, 105],
    to: [190, 280],
  },
  {
    seconds: 12,
    url: `${baseUrl}/?view=work&dialog=task&prompt=${encodeURIComponent("Add passkey sign-in end to end while preserving password login")}`,
    expect: "Describe the finished change",
    eyebrow: "02  OUTCOME",
    title: "Describe the outcome — not the agent",
    body: "Choose a repository. Agent: Auto routes the work from evidence.",
    from: [720, 215],
    to: [730, 560],
  },
  {
    seconds: 12,
    url: `${baseUrl}/?film=plan#project/${encodeURIComponent(args["project-id"])}`,
    expect: "Repository status",
    eyebrow: "03  PLAN",
    title: "A plan becomes an execution graph",
    body: "Dependencies make safe parallel work and the critical path explicit.",
    from: [760, 350],
    to: [1080, 500],
  },
  {
    seconds: 10,
    url: `${baseUrl}/?view=attention`,
    expect: "Needs You",
    eyebrow: "04  NEEDS YOU",
    title: "Human attention is the scarce resource",
    body: "Questions, gates, and recovery actions are grouped by task.",
    from: [250, 260],
    to: [1080, 380],
  },
  {
    seconds: 15,
    url: `${baseUrl}/?film=review#task/${encodeURIComponent(args["review-run-id"])}`,
    expect: "Guard the factor pipeline against look-ahead bias",
    eyebrow: "05  VERIFY",
    title: "Agents do not grade their own work",
    body: "Checks, independent review, risk, and evidence lead the decision.",
    from: [800, 280],
    to: [1040, 600],
  },
  {
    seconds: 12,
    url: `${baseUrl}/?film=delivery#task/${encodeURIComponent(args["accepted-run-id"])}`,
    expect: "Make webhook delivery idempotent",
    eyebrow: "06  DELIVER",
    title: "Accepted is not delivered",
    body: "The exact artifact stays preserved until you apply it or open a PR.",
    from: [1040, 185],
    to: [1070, 540],
  },
  {
    seconds: 12,
    url: `${baseUrl}/?view=portfolio`,
    expect: "Delivery, not activity.",
    eyebrow: "07  OUTCOMES",
    title: "Measure delivery — not activity",
    body: "Track outcomes, first-pass rate, cost, failures, and intervention.",
    from: [740, 280],
    to: [1070, 500],
  },
  {
    seconds: 8,
    url: `${baseUrl}/?view=portfolio`,
    expect: "Delivery, not activity.",
    eyebrow: "ODYSSEUS",
    title: "The delivery system for coding agents",
    body: "Local-first. Terminal-first. Evidence all the way to delivery.",
    from: [1180, 92],
    to: [1180, 92],
  },
];

await mkdir(args["frames-dir"], { recursive: true });
const chrome = spawn(
  args.chrome,
  [
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--force-device-scale-factor=1",
    `--window-size=${width},${height}`,
    "--remote-debugging-port=0",
    `--user-data-dir=${args["profile-dir"]}`,
    "about:blank",
  ],
  { stdio: ["ignore", "ignore", "pipe"] },
);

const debuggerUrl = await new Promise((resolve, reject) => {
  let buffer = "";
  const timeout = setTimeout(() => reject(new Error("Chrome DevTools endpoint did not start")), 10000);
  chrome.stderr.setEncoding("utf8");
  chrome.stderr.on("data", (chunk) => {
    buffer += chunk;
    const match = buffer.match(/DevTools listening on (ws:\/\/[^\s]+)/);
    if (match) {
      clearTimeout(timeout);
      resolve(match[1]);
    }
  });
  chrome.once("exit", (code) => reject(new Error(`Chrome exited before capture (${code})`)));
});

const client = new CDPClient(debuggerUrl);
let frameNumber = 0;
let sessionId = "";

async function page(method, params = {}) {
  return client.send(method, params, sessionId);
}

async function evaluate(expression) {
  const result = await page("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.text || "browser evaluation failed";
    throw new Error(detail);
  }
  return result;
}

async function navigate(url, expectedText) {
  await page("Page.navigate", { url });
  let ready = false;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const expectation = JSON.stringify(expectedText);
    const result = await evaluate(`document.readyState === 'complete' && document.body && document.body.innerText.includes(${expectation})`);
    if (result.result?.value) {
      ready = true;
      break;
    }
    await wait(100);
  }
  if (!ready) throw new Error(`scene did not render expected text: ${expectedText}`);
  await evaluate("document.fonts && document.fonts.ready");
  await wait(700);
}

const overlayCSS = `
  #odysseus-film-overlay { position: fixed; inset: 0; z-index: 2147483647; pointer-events: none; font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  #odysseus-film-caption { position: absolute; left: 50%; bottom: 28px; width: min(1040px, calc(100vw - 64px)); transform: translateX(-50%); box-sizing: border-box; padding: 18px 24px 19px; border: 1px solid rgba(24,24,27,.16); border-radius: 14px; background: rgba(250,250,249,.94); box-shadow: 0 18px 55px rgba(24,24,27,.17); backdrop-filter: blur(16px); color: #18181b; opacity: 0; transition: none; }
  #odysseus-film-eyebrow { color: #a3314d; font-size: 11px; line-height: 1; font-weight: 760; letter-spacing: .15em; }
  #odysseus-film-title { margin-top: 8px; font-size: 25px; line-height: 1.08; font-weight: 690; letter-spacing: -.025em; }
  #odysseus-film-body { margin-top: 6px; color: #5b5b61; font-size: 14px; line-height: 1.35; }
  #odysseus-film-scene { position: absolute; right: 23px; top: 20px; color: #8a8a90; font: 650 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
  #odysseus-film-progress { position: absolute; left: 0; top: 0; height: 3px; width: 0; background: #a3314d; border-radius: 14px 14px 0 0; }
  #odysseus-film-cursor { position: absolute; left: 0; top: 0; width: 20px; height: 20px; border: 2px solid #a3314d; border-radius: 999px; background: rgba(163,49,77,.12); box-shadow: 0 2px 14px rgba(163,49,77,.28); transform: translate(-50%, -50%); }
  #odysseus-film-cursor::after { content: ''; position: absolute; inset: 5px; border-radius: inherit; background: #a3314d; }
`;

async function installOverlay(scene, sceneIndex) {
  const payload = JSON.stringify({ ...scene, sceneIndex, sceneCount: scenes.length });
  const sceneNumber = `${String(sceneIndex + 1).padStart(2, "0")} / ${String(scenes.length).padStart(2, "0")}`;
  const markup = `
    <div id="odysseus-film-caption">
      <div id="odysseus-film-progress"></div>
      <div id="odysseus-film-scene">${sceneNumber}</div>
      <div id="odysseus-film-eyebrow"></div>
      <div id="odysseus-film-title"></div>
      <div id="odysseus-film-body"></div>
    </div>
    <div id="odysseus-film-cursor"></div>`;
  const { frameTree } = await page("Page.getFrameTree");
  const { styleSheetId } = await page("CSS.createStyleSheet", { frameId: frameTree.frame.id });
  await page("CSS.setStyleSheetText", { styleSheetId, text: overlayCSS });
  await evaluate(`(() => {
    document.getElementById('odysseus-film-overlay')?.remove();
    const data = ${payload};
    const root = document.createElement('div');
    root.id = 'odysseus-film-overlay';
    root.innerHTML = ${JSON.stringify(markup)};
    document.body.appendChild(root);
    document.getElementById('odysseus-film-eyebrow').textContent = data.eyebrow;
    document.getElementById('odysseus-film-title').textContent = data.title;
    document.getElementById('odysseus-film-body').textContent = data.body;
  })()`);
  const installed = await evaluate("Boolean(document.getElementById('odysseus-film-caption'))");
  if (!installed.result?.value) throw new Error("walkthrough overlay was not installed");
}

try {
  const { targetId } = await client.send("Target.createTarget", { url: "about:blank" });
  ({ sessionId } = await client.send("Target.attachToTarget", { targetId, flatten: true }));
  await page("Page.enable");
  await page("Runtime.enable");
  await page("DOM.enable");
  await page("CSS.enable");
  await page("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
  });

  const totalFrames = Math.round(scenes.reduce((sum, scene) => sum + scene.seconds, 0) * durationScale * fps);
  for (let sceneIndex = 0; sceneIndex < scenes.length; sceneIndex += 1) {
    const scene = scenes[sceneIndex];
    await navigate(scene.url, scene.expect);
    await installOverlay(scene, sceneIndex);
    const sceneFrames = Math.max(1, Math.round(scene.seconds * durationScale * fps));
    for (let index = 0; index < sceneFrames; index += 1) {
      const phase = sceneFrames <= 1 ? 1 : index / (sceneFrames - 1);
      const eased = phase < 0.5 ? 2 * phase * phase : 1 - ((-2 * phase + 2) ** 2) / 2;
      const x = scene.from[0] + (scene.to[0] - scene.from[0]) * eased;
      const y = scene.from[1] + (scene.to[1] - scene.from[1]) * eased;
      const opacity = Math.min(1, phase * 5, (1 - phase) * 5);
      const progress = ((frameNumber + 1) / totalFrames) * 100;
      await evaluate(`(() => {
        const caption = document.getElementById('odysseus-film-caption');
        const cursor = document.getElementById('odysseus-film-cursor');
        const bar = document.getElementById('odysseus-film-progress');
        if (caption) caption.style.opacity = '${opacity.toFixed(3)}';
        if (cursor) { cursor.style.left = '${x.toFixed(1)}px'; cursor.style.top = '${y.toFixed(1)}px'; }
        if (bar) bar.style.width = '${progress.toFixed(3)}%';
      })()`);
      const capture = await page("Page.captureScreenshot", {
        format: "jpeg",
        quality: 84,
        fromSurface: true,
        captureBeyondViewport: false,
      });
      frameNumber += 1;
      const filename = `frame-${String(frameNumber).padStart(5, "0")}.jpg`;
      await writeFile(`${args["frames-dir"]}/${filename}`, Buffer.from(capture.data, "base64"));
    }
  }
  process.stdout.write(`${frameNumber}\n`);
} finally {
  client.close();
  chrome.kill("SIGTERM");
}
