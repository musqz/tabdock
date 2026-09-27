"use strict";

// Talks to the panel through the native-messaging relay (lib/native-host).
// The relay waits for the panel itself and asks us to "resync" whenever the
// panel (re)connects, so we never push state unprompted while nobody listens.

const HOST = "openbox_sidepanel";
const RECONNECT_MS = 3000; // only needed if the relay process itself died
const DEBOUNCE_MS = 50;

let port = null;
let panelUp = false; // relay has a panel connected (set by resync, cleared by panel_disconnected)
let reconnectTimer = null;
let pushTimer = null;
let lastFocusedWindowId = null;

// Firefox cannot reorder containers, so the user's order of the panel's container sections is kept
// here (cookieStoreIds, per browser profile) and sent along with every snapshot.
let containerOrder = [];
let orderLoaded = false;

async function loadOrder() {
  if (orderLoaded) return;
  const stored = await browser.storage.local.get("containerOrder");
  containerOrder = Array.isArray(stored.containerOrder) ? stored.containerOrder : [];
  orderLoaded = true;
}

function send(msg) {
  if (port) port.postMessage(msg);
}

async function snapshot() {
  const windows = await browser.windows.getAll({ populate: true });
  let containers = [];
  try {
    containers = (await browser.contextualIdentities.query({})) || [];
  } catch (e) {
    // containers disabled (privacy.userContext.enabled = false)
  }
  await loadOrder();
  return {
    type: "state",
    focusedWindowId: lastFocusedWindowId,
    containerOrder,
    containers: containers.map((c) => ({
      cookieStoreId: c.cookieStoreId,
      name: c.name,
      color: c.color,
      colorCode: c.colorCode,
      icon: c.icon,
    })),
    windows: windows.map((w) => ({
      id: w.id,
      focused: w.focused,
      tabs: w.tabs.map((t) => ({
        id: t.id,
        index: t.index,
        title: t.title,
        url: t.url,
        favIconUrl: t.favIconUrl,
        cookieStoreId: t.cookieStoreId,
        active: t.active,
        pinned: t.pinned,
        audible: t.audible,
        discarded: t.discarded,
      })),
    })),
  };
}

// Full snapshot on every change, debounced: simple and self-healing.
function push() {
  if (!port || !panelUp || pushTimer) return;
  pushTimer = setTimeout(async () => {
    pushTimer = null;
    try {
      send(await snapshot());
    } catch (e) {
      console.error("sidepanel: snapshot failed", e);
    }
  }, DEBOUNCE_MS);
}

async function resync() {
  const info = await browser.runtime.getBrowserInfo();
  if (lastFocusedWindowId === null) {
    lastFocusedWindowId = (await browser.windows.getLastFocused()).id;
  }
  panelUp = true;
  send({ type: "hello", browser: info.name, version: info.version });
  send(await snapshot());
}

async function onCommand(msg) {
  try {
    switch (msg.type) {
      case "resync":
        await resync();
        break;
      case "panel_disconnected":
        panelUp = false;
        break;
      case "set_container_order":
        containerOrder = (msg.order || []).filter((id) => typeof id === "string");
        orderLoaded = true;
        await browser.storage.local.set({ containerOrder });
        push();
        break;
      case "move_tab":
        // index is the tab's final position in its window; tabs.onMoved then triggers a snapshot
        if (Number.isInteger(msg.tabId) && Number.isInteger(msg.index)) {
          await browser.tabs.move(msg.tabId, { index: msg.index });
        }
        break;
      case "activate_tab":
        await browser.tabs.update(msg.tabId, { active: true });
        await browser.windows.update(msg.windowId, { focused: true });
        break;
      case "new_tab":
        await browser.tabs.create({ cookieStoreId: msg.cookieStoreId, windowId: msg.windowId });
        break;
      default:
        console.warn("sidepanel: unknown command", msg.type);
    }
  } catch (e) {
    console.error("sidepanel: command failed", msg, e);
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, RECONNECT_MS);
}

function connect() {
  try {
    port = browser.runtime.connectNative(HOST);
  } catch (e) {
    console.error("sidepanel: connectNative failed", e);
    port = null;
    scheduleReconnect();
    return;
  }
  port.onMessage.addListener(onCommand);
  port.onDisconnect.addListener((p) => {
    console.warn("sidepanel: relay disconnected", p.error && p.error.message);
    port = null;
    panelUp = false;
    scheduleReconnect();
  });
}

browser.tabs.onCreated.addListener(push);
browser.tabs.onRemoved.addListener(push);
browser.tabs.onMoved.addListener(push);
browser.tabs.onActivated.addListener(push);
browser.tabs.onAttached.addListener(push);
browser.tabs.onDetached.addListener(push);
browser.tabs.onUpdated.addListener(push, {
  properties: ["title", "favIconUrl", "pinned", "audible", "discarded", "url"],
});
browser.windows.onCreated.addListener(push);
browser.windows.onRemoved.addListener(push);
browser.windows.onFocusChanged.addListener((id) => {
  // WINDOW_ID_NONE means focus left the browser: keep the last real window
  if (id !== browser.windows.WINDOW_ID_NONE) lastFocusedWindowId = id;
  push();
});
if (browser.contextualIdentities) {
  browser.contextualIdentities.onCreated.addListener(push);
  browser.contextualIdentities.onUpdated.addListener(push);
  browser.contextualIdentities.onRemoved.addListener(push);
}

connect();
