const SPLASH_MS = 4400;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const splash = document.getElementById("splash");
const home = document.getElementById("home");
const wire = document.getElementById("wire");
const message = document.getElementById("message");

const state = { mac: "idle", pc: "idle" };

function endSplash() {
  if (!splash.isConnected || splash.classList.contains("leave")) return;
  splash.classList.add("leave");
  setTimeout(() => home.classList.add("show"), 250);
  setTimeout(() => splash.remove(), 1000);
  runDemo();
}

setTimeout(endSplash, reduceMotion ? 500 : SPLASH_MS);
splash.addEventListener("click", endSplash);
addEventListener("keydown", endSplash, { once: true });

function messageFor({ mac, pc }) {
  if (mac === "connected" && pc === "connected") return "Connected. Copy on one, paste on the other.";
  if (pc === "connecting") return "Connecting to your PC…";
  if (mac === "connected") return "Waiting for your PC…";
  if (mac === "connecting") return "Starting up…";
  return "Not connected";
}

function setMessage(text) {
  if (message.textContent === text) return;
  message.classList.add("swap");
  setTimeout(() => {
    message.textContent = text;
    message.classList.remove("swap");
  }, 250);
}

function setStatus(device, value) {
  state[device] = value;
  const figure = document.getElementById(device);
  figure.dataset.state = value;
  figure.querySelector(".status").dataset.state = value;

  const both = state.mac === "connected" && state.pc === "connected";
  const busy = state.mac === "connecting" || state.pc === "connecting";
  wire.dataset.state = both ? "connected" : busy ? "connecting" : "idle";
  setMessage(messageFor(state));
}

window.copycat = { setStatus };

// Placeholder until the sync engine drives these states.
function runDemo() {
  const steps = [
    [600, "mac", "connecting"],
    [1900, "mac", "connected"],
    [3000, "pc", "connecting"],
    [5600, "pc", "connected"],
  ];
  for (const [delay, device, value] of steps) {
    setTimeout(() => setStatus(device, value), delay);
  }
}
