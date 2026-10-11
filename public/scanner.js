// Live barcode scanning from the camera.
//
// Native BarcodeDetector where it exists (Chrome on Android) — fast and free.
// Everywhere else (iOS Safari, Firefox) we lazy-load ZXing from a CDN and
// decode a cropped frame every ~150ms. Either way a code has to be read twice
// in a row and pass the GTIN checksum before we trust it: one-frame misreads
// of EAN-13s are surprisingly common.

const ZXING_URL = "https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js";
const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];
const INTERVAL_MS = 150;

let zxingPromise = null;
function loadZXing() {
  if (window.ZXing) return Promise.resolve(window.ZXing);
  zxingPromise ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = ZXING_URL;
    s.async = true;
    s.onload = () => resolve(window.ZXing);
    s.onerror = () => { zxingPromise = null; reject(new Error("Couldn't load the barcode decoder.")); };
    document.head.appendChild(s);
  });
  return zxingPromise;
}

/** GTIN (EAN-8/UPC-A/EAN-13/GTIN-14) mod-10 check. */
export function validGtin(code) {
  if (!/^\d+$/.test(code) || ![8, 12, 13, 14].includes(code.length)) return false;
  const digits = code.split("").map(Number);
  const check = digits.pop();
  const sum = digits.reverse().reduce((acc, d, i) => acc + d * (i % 2 === 0 ? 3 : 1), 0);
  return (10 - (sum % 10)) % 10 === check;
}

async function nativeDetector() {
  if (!("BarcodeDetector" in window)) return null;
  try {
    const supported = await window.BarcodeDetector.getSupportedFormats();
    const formats = FORMATS.filter((f) => supported.includes(f));
    if (!formats.includes("ean_13")) return null;
    const detector = new window.BarcodeDetector({ formats });
    return async (video) => {
      const found = await detector.detect(video);
      return found.length ? { text: found[0].rawValue, format: found[0].format } : null;
    };
  } catch {
    return null;
  }
}

async function zxingDetector() {
  const Z = await loadZXing();
  const hints = new Map();
  hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [
    Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.UPC_E,
  ]);
  hints.set(Z.DecodeHintType.TRY_HARDER, true);
  const reader = new Z.MultiFormatReader();
  reader.setHints(hints);
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const names = { [Z.BarcodeFormat.UPC_E]: "upc_e" };

  return async (video) => {
    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh) return null;
    // decode only the band under the on-screen reticle: faster and fewer false hits
    const sw = vw * 0.85, sh = vh * 0.45;
    const scale = Math.min(1, 900 / sw);
    canvas.width = Math.round(sw * scale);
    canvas.height = Math.round(sh * scale);
    ctx.drawImage(video, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, canvas.width, canvas.height);
    try {
      const bitmap = new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.HTMLCanvasElementLuminanceSource(canvas)));
      const res = reader.decodeWithState(bitmap);
      return { text: res.getText(), format: names[res.getBarcodeFormat()] || "ean" };
    } catch {
      return null; // NotFoundException on most frames — that's normal
    } finally {
      reader.reset();
    }
  };
}

/**
 * Start scanning into `video`. Calls onCode(code) once, then stops itself.
 * Returns { stop, torch } — torch is null when the camera has no flashlight.
 */
export async function startScanner(video, { onCode, onStatus }) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("This browser can't access the camera. Type the barcode instead.");
  }
  if (!window.isSecureContext) {
    throw new Error("The camera only works over HTTPS (or on localhost).");
  }

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
    });
  } catch (e) {
    if (e.name === "NotAllowedError") {
      throw new Error("Camera permission was denied. Allow camera access for this site in your browser settings, or type the barcode below.");
    }
    if (e.name === "NotFoundError" || e.name === "OverconstrainedError") {
      throw new Error("No camera found on this device. Type the barcode below.");
    }
    throw new Error(`Couldn't start the camera (${e.name || e.message}).`);
  }

  let stopped = false;
  let timer = null;
  const track = stream.getVideoTracks()[0];
  const stop = () => {
    stopped = true;
    clearTimeout(timer);
    stream.getTracks().forEach((t) => t.stop());
    video.srcObject = null;
  };

  video.setAttribute("playsinline", "");
  video.muted = true;
  video.srcObject = stream;
  try { await video.play(); } catch { /* autoplay quirks: frames still arrive */ }

  onStatus?.("Starting decoder…");
  let detect;
  try {
    detect = (await nativeDetector()) || (await zxingDetector());
  } catch (e) {
    stop();
    throw e;
  }
  if (stopped) return { stop, torch: null };
  onStatus?.("Point at a barcode — hold steady");

  let last = null;
  const tick = async () => {
    if (stopped) return;
    try {
      if (video.readyState >= 2) {
        const hit = await detect(video);
        const text = hit?.text?.replace(/\D/g, "");
        // UPC-E checksums need expansion first; let the server sort those out
        const ok = text && (hit.format === "upc_e" ? text.length >= 6 : validGtin(text));
        if (ok && text === last) {
          stop();
          navigator.vibrate?.(60);
          onCode(text);
          return;
        }
        last = ok ? text : null;
      }
    } catch { /* a bad frame shouldn't kill the loop */ }
    timer = setTimeout(tick, INTERVAL_MS);
  };
  tick();

  let torch = null;
  const caps = track.getCapabilities?.() || {};
  if (caps.torch) {
    let on = false;
    torch = async () => {
      on = !on;
      await track.applyConstraints({ advanced: [{ torch: on }] });
      return on;
    };
  }
  return { stop, torch };
}
