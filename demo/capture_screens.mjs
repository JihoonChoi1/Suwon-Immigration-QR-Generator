// Captures the portfolio screenshots and a short API transcript from a real local run.
//
//   PLAYWRIGHT_FROM=/path/to/a/project/with/playwright node demo/capture_screens.mjs
//
// The script starts `manage.py runserver` from the repo's .venv on 127.0.0.1:8765, drives the page in headless
// Chrome, and stops the server when it is done (also on failure). It uses only public sample links.
// Two states cannot be produced by a healthy local server, so the script makes them happen in the browser and says so
// in the manifest: the loading state (the API response is held back for a moment) and the network-error state
// (the request is aborted as if the server were unreachable). The UI itself is the real page in both cases.
import { spawn, execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const out = join(here, "screens");
const require = createRequire(process.env.PLAYWRIGHT_FROM ? join(resolve(process.env.PLAYWRIGHT_FROM), "x.js") : import.meta.url);
const { chromium } = require("playwright");

const PORT = 8765;
const BASE = `http://127.0.0.1:${PORT}`;
const SAMPLE = "https://github.com/JihoonChoi1/Suwon-Immigration-QR-Generator";
const NO_SCHEME = "drive.google.com/file/d/sample/view";

const git = (...args) => execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForServer() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`${BASE}/api/health`);
      if (r.ok) return;
    } catch (_) { /* not up yet */ }
    await sleep(250);
  }
  throw new Error("server did not start");
}

async function api(body) {
  const r = await fetch(`${BASE}/api/qr`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return { request: body, status: r.status, response: await r.json() };
}

const server = spawn(join(root, ".venv/bin/python"), ["manage.py", "runserver", `127.0.0.1:${PORT}`, "--noreload"], {
  cwd: root, stdio: ["ignore", "ignore", "pipe"], env: { ...process.env, DJANGO_DEBUG: "1" },
});
let browser;
const shots = [];

try {
  await waitForServer();
  mkdirSync(out, { recursive: true });
  browser = await chromium.launch({ channel: "chrome" });

  async function page(viewport, scheme = "light") {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, colorScheme: scheme, locale: "ko-KR",
      acceptDownloads: true, reducedMotion: "reduce" });
    const p = await ctx.newPage();
    await p.goto(BASE);
    return { ctx, p };
  }
  async function shot(p, name, note) {
    await sleep(150);
    await p.screenshot({ path: join(out, name) });
    shots.push({ file: `screens/${name}`, note });
  }
  async function generate(p, url, level) {
    await p.fill("#url", url);
    if (level) await p.check(`input[name="ec"][value="${level}"]`);
    await p.click("#submit");
    await p.waitForSelector('#preview[data-state="success"]');
    await p.waitForFunction(() => document.getElementById("qr-img").complete);
  }

  // Desktop, light
  {
    const { ctx, p } = await page({ width: 1280, height: 860 });
    await shot(p, "01-empty.png", "First load: nothing generated yet.");

    await p.fill("#url", NO_SCHEME);
    await p.click("#submit");
    await p.waitForSelector("#url-error:not([hidden])");
    await shot(p, "02-validation-error.png", `Typed "${NO_SCHEME}" without a scheme and pressed the button.`);

    // Loading: hold the real API response back for a moment.
    let release;
    const held = new Promise((r) => (release = r));
    await p.route("**/api/qr", async (route) => { await held; await route.continue(); });
    await p.fill("#url", SAMPLE);
    await p.click("#submit");
    await p.waitForSelector('#preview[data-state="loading"]');
    await shot(p, "03-loading.png", "Loading state; the script delayed the API call so it could be photographed.");
    release();
    await p.waitForSelector('#preview[data-state="success"]');
    await p.unroute("**/api/qr");
    await p.waitForFunction(() => document.getElementById("qr-img").complete);
    await p.evaluate(() => document.getElementById("toast").classList.remove("show"));
    await shot(p, "04-success.png", `Generated for ${SAMPLE} at the default level (M).`);

    const download = p.waitForEvent("download");
    await p.click("#save-png");
    const file = await download;
    await file.saveAs(join(here, "sample-qr.png"));
    shots.push({ file: "sample-qr.png", note: `The PNG the "PNG로 저장" button saved (${file.suggestedFilename()}).` });
    await sleep(300);
    await shot(p, "05-saved-toast.png", "Right after pressing PNG로 저장: the confirmation toast.");

    await p.route("**/api/qr", (route) => route.abort("connectionrefused"));
    await p.check('input[name="ec"][value="H"]');
    await p.click("#submit");
    await p.waitForSelector('#preview[data-state="error"]');
    await p.evaluate(() => document.getElementById("toast").classList.remove("show"));
    await shot(p, "06-network-error.png", "Network error state; the script aborted the request as if the server were unreachable.");
    await p.unroute("**/api/qr");
    await ctx.close();
  }

  // Desktop, dark, highest level
  {
    const { ctx, p } = await page({ width: 1280, height: 860 }, "dark");
    await generate(p, SAMPLE, "H");
    await p.evaluate(() => document.getElementById("toast").classList.remove("show"));
    await shot(p, "07-success-dark-h.png", "Dark mode (follows the OS), highest error correction (H).");
    await ctx.close();
  }

  // Phone
  {
    const { ctx, p } = await page({ width: 390, height: 844 });
    await shot(p, "08-mobile-empty.png", "Phone width, first load.");
    await generate(p, SAMPLE);
    await p.evaluate(() => document.getElementById("toast").classList.remove("show"));
    await p.locator(".state-success").scrollIntoViewIfNeeded();
    await shot(p, "09-mobile-success.png", "Phone width, after generating (scrolled to the result).");
    await ctx.close();
  }

  // Real API exchanges, recorded as they came back.
  const exchanges = [
    await api({ url: SAMPLE }),
    await api({ url: SAMPLE, format: "svg", error_correction: "H" }),
    await api({ url: NO_SCHEME }),
    await api({ url: "javascript:alert(1)" }),
    await api({ url: "https://user:secret@example.com/file" }),
    await api({ url: SAMPLE, scale: 100 }),
  ];
  for (const e of exchanges) {
    if (e.response.data_uri) e.response.data_uri = `${e.response.data_uri.slice(0, 48)}... (${e.response.bytes} bytes, truncated here)`;
  }

  const manifest = {
    captured_at: new Date().toISOString(),
    commit: git("rev-parse", "--short", "HEAD"),
    dirty: git("status", "--porcelain").length > 0,
    server: "python manage.py runserver (DJANGO_DEBUG=1), .venv: " +
      execFileSync(join(root, ".venv/bin/python"), ["-c", "import django,segno,sys;print(f'Python {sys.version.split()[0]}, Django {django.get_version()}, segno {segno.__version__}')"], { encoding: "utf8" }).trim(),
    browser: `Chrome ${browser.version()} (headless, Playwright), deviceScaleFactor 2`,
    sample_url: SAMPLE,
    shots,
    api: exchanges,
  };
  writeFileSync(join(here, "capture.json"), JSON.stringify(manifest, null, 2) + "\n");
  console.log(`saved ${shots.length} files and capture.json (commit ${manifest.commit}, dirty ${manifest.dirty})`);
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
}
