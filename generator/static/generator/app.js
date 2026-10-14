// QR generator front end: sends the link to POST /api/qr and shows what comes back.
// The server does the encoding; this file only handles input, the four preview states and saving/copying.
(() => {
  "use strict";

  const API = document.body.dataset.api;
  const MAX_LENGTH = Number(document.body.dataset.maxLength) || 1024;
  const TIMEOUT_MS = 10000;

  const MESSAGES = {
    missing_url: "링크를 입력하세요.",
    missing_scheme: "http:// 또는 https://로 시작하는 전체 주소를 입력하세요.",
    unsupported_scheme: "http 또는 https 링크만 QR 코드로 만들 수 있습니다.",
    invalid_url: "올바른 링크 형식이 아닙니다. 주소를 다시 확인하세요.",
    url_too_long: `링크가 너무 깁니다. ${MAX_LENGTH}자 이하로 줄여 주세요.`,
    credentials_in_url: "아이디나 비밀번호가 들어 있는 링크는 QR 코드로 만들 수 없습니다.",
    network: "서버에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도하세요.",
    timeout: "서버 응답이 너무 늦습니다. 잠시 후 다시 시도하세요.",
    server: "서버에서 오류가 발생했습니다. 잠시 후 다시 시도하세요.",
  };
  const LEVEL_NAMES = { L: "낮음", M: "보통", Q: "높음", H: "최고" };

  const $ = (id) => document.getElementById(id);
  const form = $("qr-form");
  const input = $("url");
  const clearBtn = $("url-clear");
  const countValue = $("url-count-value");
  const countBox = $("url-count");
  const fieldError = $("url-error");
  const submitBtn = $("submit");
  const preview = $("preview");
  const previewError = $("preview-error-text");
  const img = $("qr-img");
  const qrUrl = $("qr-url");
  const qrInfo = $("qr-info");
  const stale = $("stale");
  const toast = $("toast");
  const copyImageBtn = $("copy-image");

  let current = null;      // the last successful response: { url, error_correction, data_uri, ... }
  let lastRequest = null;  // { url, ec } of the last request sent, for "다시 시도"
  let inflight = null;     // AbortController of the request in progress
  let toastTimer = 0;

  const canCopyImage = Boolean(navigator.clipboard && window.ClipboardItem && window.isSecureContext);
  copyImageBtn.hidden = !canCopyImage;

  // ---- helpers ----

  class ApiError extends Error {
    constructor(code, message, field) {
      super(message);
      this.code = code;
      this.field = field;
    }
  }

  function selectedLevel() {
    return form.querySelector('input[name="ec"]:checked').value;
  }

  function setState(state) {
    preview.dataset.state = state;
    preview.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  }

  function setBusy(busy) {
    submitBtn.disabled = busy;
    submitBtn.classList.toggle("is-loading", busy);
  }

  function showFieldError(message) {
    fieldError.textContent = message;
    fieldError.hidden = false;
    input.setAttribute("aria-invalid", "true");
  }

  function clearFieldError() {
    fieldError.hidden = true;
    fieldError.textContent = "";
    input.removeAttribute("aria-invalid");
  }

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 2400);
  }

  function updateMeta() {
    const length = input.value.trim().length;
    countValue.textContent = String(length);
    countBox.classList.toggle("over", length > MAX_LENGTH);
    clearBtn.hidden = input.value.length === 0;
    stale.hidden = !current || (input.value.trim() === current.url && selectedLevel() === current.error_correction);
  }

  /** The same first checks the server makes, so obvious mistakes never leave the page. */
  function localCheck(url) {
    if (!url) return "missing_url";
    if (url.length > MAX_LENGTH) return "url_too_long";
    if (/\s/.test(url)) return "invalid_url";
    const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(url);
    if (!scheme || scheme[1].includes(".") || /^\d/.test(url.slice(scheme[0].length))) return "missing_scheme";
    if (!/^https?$/i.test(scheme[1])) return "unsupported_scheme";
    return null;
  }

  function dataUriToBlob(dataUri) {
    // Decoded by hand: the page's CSP does not allow fetch() on data: URIs.
    const [head, base64] = dataUri.split(",", 2);
    const mime = head.slice(5, head.indexOf(";"));
    const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    return new Blob([bytes], { type: mime });
  }

  function fileName(url, ext) {
    let host = "link";
    try {
      host = new URL(url).hostname.replace(/[^a-z0-9.-]/gi, "_") || host;
    } catch (_) { /* keep the default */ }
    return `qr_${host}.${ext}`;
  }

  function download(blob, name) {
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  }

  async function requestQr(url, ec, format) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort("timeout"), TIMEOUT_MS);
    if (format === "png") {
      if (inflight) inflight.abort("replaced");
      inflight = controller;
    }
    let response;
    try {
      response = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ url, format, error_correction: ec }),
        signal: controller.signal,
      });
    } catch (err) {
      if (controller.signal.reason === "replaced") throw new ApiError("replaced");
      throw new ApiError(controller.signal.reason === "timeout" ? "timeout" : "network");
    } finally {
      clearTimeout(timer);
      if (inflight === controller) inflight = null;
    }
    let body = null;
    try {
      body = await response.json();
    } catch (_) { /* a proxy error page, for example */ }
    if (!response.ok || !body) {
      const e = body && body.error;
      throw new ApiError(e ? e.code : "server", e ? e.message : "", e ? e.field : undefined);
    }
    return body;
  }

  // ---- generate ----

  async function generate(url, ec) {
    lastRequest = { url, ec };
    clearFieldError();
    setBusy(true);
    setState("loading");
    try {
      const result = await requestQr(url, ec, "png");
      current = result;
      img.src = result.data_uri;
      img.alt = `QR 코드: ${result.url}`;
      qrUrl.textContent = result.url;
      const parts = [
        `버전 ${result.version}`,
        `${result.modules}×${result.modules} 모듈`,
        `오류 복원 ${LEVEL_NAMES[result.error_correction] || result.error_correction}(${result.error_correction})`,
        `${result.size_px}×${result.size_px} px`,
      ];
      qrInfo.replaceChildren(...parts.flatMap((text, i) => {
        const span = document.createElement("span");
        span.className = "nowrap";
        span.textContent = text;
        return i ? [" · ", span] : [span];
      }));
      setState("success");
      updateMeta();
      showToast("QR 코드를 만들었습니다.");
    } catch (err) {
      if (err.code === "replaced") return;
      if (err.field === "url" || err.field === "error_correction") {
        // A problem with what was typed: say so next to the field and keep the previous result, if any.
        setState(current ? "success" : "empty");
        showFieldError(MESSAGES[err.code] || MESSAGES.invalid_url);
        input.focus();
      } else {
        previewError.textContent = MESSAGES[err.code] || MESSAGES.server;
        setState("error");
      }
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const url = input.value.trim();
    const problem = localCheck(url);
    if (problem) {
      showFieldError(MESSAGES[problem]);
      input.focus();
      return;
    }
    generate(url, selectedLevel());
  });

  $("retry").addEventListener("click", () => {
    if (lastRequest) generate(lastRequest.url, lastRequest.ec);
  });

  input.addEventListener("input", () => {
    if (!fieldError.hidden) clearFieldError();
    updateMeta();
  });
  form.addEventListener("change", updateMeta);

  clearBtn.addEventListener("click", () => {
    input.value = "";
    clearFieldError();
    updateMeta();
    input.focus();
  });

  // ---- save and copy ----

  $("save-png").addEventListener("click", () => {
    if (!current) return;
    download(dataUriToBlob(current.data_uri), fileName(current.url, "png"));
    showToast("PNG 파일을 저장했습니다.");
  });

  $("save-svg").addEventListener("click", async (event) => {
    if (!current) return;
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const svg = await requestQr(current.url, current.error_correction, "svg");
      download(dataUriToBlob(svg.data_uri), fileName(current.url, "svg"));
      showToast("SVG 파일을 저장했습니다.");
    } catch (err) {
      showToast(MESSAGES[err.code] || MESSAGES.server);
    } finally {
      button.disabled = false;
    }
  });

  copyImageBtn.addEventListener("click", async () => {
    if (!current) return;
    try {
      await navigator.clipboard.write([new ClipboardItem({ "image/png": dataUriToBlob(current.data_uri) })]);
      showToast("QR 이미지를 클립보드에 복사했습니다.");
    } catch (_) {
      showToast("이미지를 복사하지 못했습니다. ‘PNG로 저장’을 이용하세요.");
    }
  });

  $("copy-url").addEventListener("click", async () => {
    if (!current) return;
    try {
      await navigator.clipboard.writeText(current.url);
      showToast("링크를 복사했습니다.");
    } catch (_) {
      showToast("링크를 복사하지 못했습니다.");
    }
  });

  updateMeta();
})();
