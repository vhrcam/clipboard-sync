const SPLASH_MS = 4400;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (id) => document.getElementById(id);

const splash = $("splash");
const home = $("home");
const wire = $("wire");
const message = $("message");
const pairing = $("pairing");
const connectForm = $("connect-form");
const connectInput = $("connect-input");
const showConnect = $("show-connect");

let state = null;
let bridged = false;
let flashing = false;
let flashTimer = null;

const api = () => window.pywebview?.api;

// ---------- Launch animation ----------

function endSplash() {
  if (!splash.isConnected || splash.classList.contains("leave")) return;
  splash.classList.add("leave");
  setTimeout(() => home.classList.add("show"), 250);
  setTimeout(() => splash.remove(), 1000);
}

setTimeout(endSplash, reduceMotion ? 500 : SPLASH_MS);
splash.addEventListener("click", endSplash);
addEventListener("keydown", endSplash, { once: true });

// ---------- Rendering ----------

const kindOf = (os) => (os === "mac" ? "Mac" : "PC");

function setDevice(figure, { os, label, status }) {
  figure.dataset.os = os;
  figure.dataset.state = status;
  figure.querySelector(".status").dataset.state = status;
  figure.querySelector(".name").textContent = label;
}

function statusMessage(s) {
  if (s.error) return s.error;
  if (s.self.state === "starting") return "Starting up…";
  if (!s.peer) return "Looking for your other computer on this Wi-Fi…";
  if (s.peer.state === "connected") return `Connected to ${s.peer.name}. Copy on one, paste on the other.`;
  return "Connecting…";
}

function setMessage(text, alert = false) {
  if (message.textContent === text) {
    message.classList.toggle("alert", alert);
    return;
  }
  message.classList.add("swap");
  setTimeout(() => {
    message.textContent = text;
    message.classList.toggle("alert", alert);
    message.classList.remove("swap");
  }, 200);
}

function flash(text, ms = 3200, alert = false) {
  flashing = true;
  clearTimeout(flashTimer);
  setMessage(text, alert);
  flashTimer = setTimeout(() => {
    flashing = false;
    render();
  }, ms);
}

function render() {
  if (!state) return;
  const { self: me, peer, pairing: pair } = state;
  const otherOs = me.os === "mac" ? "windows" : "mac";

  setDevice($("self"), {
    os: me.os,
    label: `This ${kindOf(me.os)}`,
    status: me.state === "ready" ? "connected" : me.state === "starting" ? "connecting" : "idle",
  });
  setDevice($("peer"), {
    os: peer?.os ?? otherOs,
    label: peer?.name ?? `Your ${kindOf(otherOs)}`,
    status: !peer ? "idle" : peer.state === "connected" ? "connected" : "connecting",
  });

  const bothConnected = me.state === "ready" && peer?.state === "connected";
  wire.dataset.state = bothConnected ? "connected" : peer ? "connecting" : "idle";

  pairing.hidden = !pair;
  message.hidden = Boolean(pair);
  if (pair) {
    $("pair-name").textContent = peer?.name ?? "this computer";
    $("pair-code").textContent = pair.code;
    $("pair-actions").hidden = pair.waiting;
    $("pair-wait").hidden = !pair.waiting;
  }

  $("self-ip").textContent = `This ${kindOf(me.os)}: ${me.ip}`;
  $("unpair").hidden = peer?.state !== "connected";

  if (!flashing) setMessage(statusMessage(state), Boolean(state.error));
}

function pulse(direction) {
  wire.classList.remove("out", "in");
  void wire.offsetWidth;
  wire.classList.add(direction);
}

function onEvent(e) {
  if (e.kind === "sent" || e.kind === "received") {
    pulse(e.kind === "sent" ? "out" : "in");
    flash(`${e.kind === "sent" ? "Sent to" : "Got from"} ${e.peer}: “${e.preview}”`);
  } else if (e.kind === "notice") {
    flash(e.text, 5000, true);
  }
}

window.copycat = {
  update(next) {
    state = next;
    render();
  },
  event: onEvent,
};

// ---------- Controls ----------

function hideConnectForm() {
  connectForm.hidden = true;
  showConnect.hidden = false;
  connectInput.value = "";
}

$("pair-yes").addEventListener("click", () => api()?.pair(true));
$("pair-no").addEventListener("click", () => api()?.pair(false));
$("unpair").addEventListener("click", () => api()?.unpair());

showConnect.addEventListener("click", () => {
  showConnect.hidden = true;
  connectForm.hidden = false;
  connectInput.focus();
});

connectForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const address = connectInput.value.trim();
  if (address) api()?.connect(address);
  hideConnectForm();
});

connectInput.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hideConnectForm();
});

// ---------- Python bridge ----------

function connectBridge() {
  if (bridged) return;
  bridged = true;
  api().ready().then(window.copycat.update);
}

if (api()?.ready) connectBridge();
else addEventListener("pywebviewready", connectBridge);

// Opened in a normal browser (no Python): play sample states so the screens can be previewed.
setTimeout(() => {
  if (!bridged) runPreview(new URLSearchParams(location.search).get("preview"));
}, 1500);

function runPreview(mode) {
  const me = { name: "MacBook Air", os: "mac", ip: "192.168.1.33", port: 8765 };
  const pc = { name: "Windows PC", os: "windows" };
  const at = (selfState, peerState) => ({
    self: { ...me, state: selfState },
    peer: peerState ? { ...pc, state: peerState } : null,
    pairing: peerState === "pairing" ? { code: "482 913", waiting: false } : null,
    error: null,
  });
  const timeline = mode === "pairing"
    ? [[0, at("starting")], [700, at("ready")], [1800, at("ready", "connecting")], [2600, at("ready", "pairing")]]
    : [[0, at("starting")], [700, at("ready")], [1900, at("ready", "connecting")], [4300, at("ready", "connected")]];
  for (const [ms, snapshot] of timeline) setTimeout(() => window.copycat.update(snapshot), ms);
}
