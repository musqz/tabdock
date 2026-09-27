"use strict";

// Talks to the panel through the native-messaging relay (lib/native-host).
// The relay waits for the panel itself and asks us to "resync" whenever the
// panel (re)connects, so we never push state unprompted while nobody listens.

// Named before the rename to tabdock and kept, like the add-on id: the browser finds the relay's
// manifest (openbox_sidepanel.json) by this name, in installs this signed file cannot update.
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

// Workspace changes and the snapshots that report them run one at a time, in the order they came:
// each reads and writes the maps below across several awaits.
let queue = Promise.resolve();

function serial(fn) {
  const run = queue.then(fn);
  queue = run.catch(() => {}); // a failure is reported by whoever awaits `run`, and never blocks the next
  return run;
}

// -- workspaces -----------------------------------------------------------------------------------
// Exclusive, as in Zen: each window shows one workspace, and the tabs of the others are hidden
// (tabs.hide), in the browser's own tab strip too. Pinned tabs cannot be hidden, so they show in every
// workspace. The list of workspaces lives in storage.local; which workspace a tab belongs to, and which
// one a window shows, live in the session (sessions.setTabValue / setWindowValue), so they survive a
// browser restart although tab and window ids change.
// Until a second workspace is created (or the first renamed) nothing is stored and no tab is ever hidden
// or shown: a profile that does not use workspaces is left exactly as it was. The panel offers none in
// Zen, which has workspaces of its own.

const WS_KEY = "workspace"; // the session value on tabs and windows
const DEFAULT_WS = { id: "default", name: "Default" };
const NAME_MAX = 64;
const ICON_MAX = 8; // characters: one emoji, even a composed one (a flag, a family), or a few letters
const COLORS = ["blue", "turquoise", "green", "yellow", "orange", "red", "pink", "purple", "toolbar"]; // as containers
// The new-tab page: a tab opened on it in no container (Ctrl+T, the tab strip's +) is what a workspace's own
// container takes over. Links, restored pages and tabs in a container keep the container they came with.
const NEW_TAB_URLS = ["about:newtab", "about:home"];
let workspaces = null; // [{id, name, icon?, color?, cookieStoreId?}] once in use; null: never used in this profile
const tabWs = new Map(); // tabId -> workspace id (the session values, cached)
const winWs = new Map(); // windowId -> the workspace it shows
let lastWs = null; // what the window focused last shows: a new window starts there

function known(id) {
  return workspaces !== null && workspaces.some((w) => w.id === id);
}

function cleanName(name) {
  return typeof name === "string" ? name.trim().slice(0, NAME_MAX) : "";
}

function cleanIcon(icon) {
  return typeof icon === "string" ? [...icon.trim()].slice(0, ICON_MAX).join("") : "";
}

function workspaceOf(id) {
  return workspaces === null ? null : workspaces.find((w) => w.id === id) || null;
}

// The container a workspace opens its new tabs in, while it still exists (null: none).
async function containerOf(id) {
  const store = (workspaceOf(id) || {}).cookieStoreId;
  if (!store) return null;
  try {
    await browser.contextualIdentities.get(store);
    return store;
  } catch (e) {
    return null; // removed since (forgetContainer drops it for good)
  }
}

async function loadWorkspaces() {
  const stored = await browser.storage.local.get("workspaces");
  const list = stored.workspaces;
  const valid = (w) => w && typeof w.id === "string" && typeof w.name === "string";
  if (!Array.isArray(list) || !list.length || !list.every(valid)) return;
  workspaces = list;
  for (const w of await browser.windows.getAll()) await reconcile(w.id); // tabs opened while we were not running
}

async function saveWorkspaces() {
  await browser.storage.local.set({ workspaces });
}

// The session values of a tab or window that is already gone read as nothing and cannot be written.
async function readTab(tabId) {
  try {
    return await browser.sessions.getTabValue(tabId, WS_KEY);
  } catch (e) {
    return undefined;
  }
}

async function readWindow(windowId) {
  try {
    return await browser.sessions.getWindowValue(windowId, WS_KEY);
  } catch (e) {
    return undefined;
  }
}

async function assign(tabId, id) {
  tabWs.set(tabId, id);
  try {
    await browser.sessions.setTabValue(tabId, WS_KEY, id);
  } catch (e) {
    // closed meanwhile
  }
}

async function showWs(windowId, id) {
  winWs.set(windowId, id);
  if (windowId === lastFocusedWindowId) lastWs = id;
  try {
    await browser.sessions.setWindowValue(windowId, WS_KEY, id);
  } catch (e) {
    // closed meanwhile
  }
}

async function windowWs(windowId) {
  let id = winWs.get(windowId);
  if (known(id)) return id;
  id = await readWindow(windowId); // restored with the window after a browser restart
  if (!known(id)) id = known(lastWs) ? lastWs : workspaces[0].id; // a new window: where you were
  await showWs(windowId, id);
  return id;
}

async function tabWsOf(tab) {
  let id = tabWs.get(tab.id);
  if (known(id)) return id;
  id = await readTab(tab.id); // restored after a browser restart, or reopened after closing it
  if (!known(id)) id = await windowWs(tab.windowId); // a new tab joins the workspace its window shows
  await assign(tab.id, id);
  return id;
}

async function getTab(tabId) {
  try {
    return await browser.tabs.get(tabId);
  } catch (e) {
    return null;
  }
}

// Hide what does not belong to the window's workspace and show what does. The active tab cannot be
// hidden, so its workspace is the one the window shows (you picked a hidden tab from the browser's
// list of all tabs, say).
async function reconcile(windowId) {
  if (workspaces === null) return;
  const tabs = await browser.tabs.query({ windowId });
  let shown = await windowWs(windowId);
  const active = tabs.find((t) => t.active && !t.pinned);
  if (active) {
    const its = await tabWsOf(active);
    if (its !== shown) {
      shown = its;
      await showWs(windowId, shown);
    }
  }
  const show = [];
  const hide = [];
  for (const tab of tabs) {
    if (tab.pinned) continue; // cannot be hidden: shows in every workspace
    const mine = (await tabWsOf(tab)) === shown;
    if (mine && tab.hidden) show.push(tab.id);
    if (!mine && !tab.hidden && !tab.active) hide.push(tab.id);
  }
  try {
    if (show.length) await browser.tabs.show(show);
    if (hide.length) await browser.tabs.hide(hide);
  } catch (e) {
    console.warn("tabdock: hiding or showing tabs failed (one was closed meanwhile?)", e); // the next change heals it
  }
}

// Make a tab of workspace `id` the active one in the window: the one you were on last in it, or a new
// tab when it has none (as in Zen, a workspace is never an empty window).
async function focusWorkspace(windowId, id) {
  let target = null;
  for (const tab of await browser.tabs.query({ windowId })) {
    if (tab.pinned || (await tabWsOf(tab)) !== id) continue;
    if (tab.active) return;
    if (target === null || tab.lastAccessed > target.lastAccessed) target = tab;
  }
  if (target === null) {
    const tab = await newTab(windowId, id);
    await assign(tab.id, id);
    return;
  }
  if (target.hidden) await browser.tabs.show(target.id);
  await browser.tabs.update(target.id, { active: true });
}

// A new, active tab for workspace `id`, in its container if it has one (and the window can hold one: a
// private window cannot).
async function newTab(windowId, id) {
  const store = await containerOf(id);
  if (store !== null) {
    try {
      return await browser.tabs.create({ windowId, active: true, cookieStoreId: store });
    } catch (e) {
      // a private window
    }
  }
  return browser.tabs.create({ windowId, active: true });
}

async function switchWorkspace(windowId, id) {
  if (!known(id)) return;
  await showWs(windowId, id);
  await focusWorkspace(windowId, id);
  await reconcile(windowId);
}

// The first workspace change stores the list; every tab and window so far is in the first workspace.
async function startUsing() {
  if (workspaces !== null) return;
  workspaces = [{ ...DEFAULT_WS }];
  for (const w of await browser.windows.getAll({ populate: true })) {
    await showWs(w.id, DEFAULT_WS.id);
    for (const t of w.tabs) await assign(t.id, DEFAULT_WS.id);
  }
}

async function newWorkspace(windowId, name) {
  await startUsing();
  const ws = { id: `ws-${crypto.randomUUID()}`, name: cleanName(name) || `Workspace ${workspaces.length + 1}` };
  workspaces.push(ws);
  await saveWorkspaces();
  await switchWorkspace(windowId, ws.id); // as in Zen: a new workspace is where you go next
}

async function renameWorkspace(id, name) {
  name = cleanName(name);
  if (!name || !(id === DEFAULT_WS.id || known(id))) return;
  await startUsing();
  const ws = workspaces.find((w) => w.id === id);
  if (!ws) return;
  ws.name = name;
  await saveWorkspaces();
}

// Its icon, colour and container, each only when `change` names it; an empty or unknown value clears it.
async function editWorkspace(id, change) {
  if (!(id === DEFAULT_WS.id || known(id))) return;
  await startUsing();
  const ws = workspaceOf(id);
  if (!ws) return;
  const set = (key, value) => {
    if (value) ws[key] = value;
    else delete ws[key];
  };
  if ("icon" in change) set("icon", cleanIcon(change.icon));
  if ("color" in change) set("color", COLORS.includes(change.color) ? change.color : "");
  if ("cookieStoreId" in change) {
    let store = typeof change.cookieStoreId === "string" ? change.cookieStoreId : "";
    try {
      if (store) await browser.contextualIdentities.get(store);
    } catch (e) {
      store = ""; // not a container (any more)
    }
    set("cookieStoreId", store);
  }
  await saveWorkspaces();
}

// A container was removed: the workspaces that opened their new tabs in it open them in none again.
async function forgetContainer(store) {
  if (workspaces === null || !workspaces.some((w) => w.cookieStoreId === store)) return;
  for (const ws of workspaces) if (ws.cookieStoreId === store) delete ws.cookieStoreId;
  await saveWorkspaces();
}

// Nothing is closed: the tabs of a removed workspace, and the windows that showed it, go to its
// neighbour in the list. The last workspace stays.
async function removeWorkspace(id) {
  if (workspaces === null || workspaces.length < 2) return;
  const at = workspaces.findIndex((w) => w.id === id);
  if (at < 0) return;
  const heir = workspaces[at > 0 ? at - 1 : 1].id;
  for (const w of await browser.windows.getAll({ populate: true })) {
    for (const t of w.tabs) if ((await tabWsOf(t)) === id) await assign(t.id, heir);
    if ((await windowWs(w.id)) === id) await showWs(w.id, heir);
  }
  if (lastWs === id) lastWs = heir;
  workspaces.splice(at, 1);
  await saveWorkspaces();
  for (const w of await browser.windows.getAll()) await reconcile(w.id);
}

async function moveToWorkspace(tabId, id) {
  const tab = await getTab(tabId);
  if (tab === null || !known(id)) return; // (with workspaces unused there is nowhere else to go)
  await assign(tab.id, id);
  const shown = await windowWs(tab.windowId);
  // an active tab cannot be hidden: stay in this workspace, on the tab you were on before it
  if (tab.active && !tab.pinned && id !== shown) await focusWorkspace(tab.windowId, shown);
  await reconcile(tab.windowId);
}

// Close a tab the panel was asked to close. While workspaces are in use, never the window with it: when the
// tab is the only one the window shows, the rest are other workspaces' hidden tabs, and Firefox would close the
// window and all of those with it (browser.tabs.closeWindowWithLastTab). The workspace gets a new tab first.
async function closeTab(tabId) {
  const tab = await getTab(tabId);
  if (tab === null) return;
  if (workspaces !== null && !tab.hidden) {
    const tabs = await browser.tabs.query({ windowId: tab.windowId });
    if (tabs.some((t) => t.hidden) && tabs.every((t) => t.id === tab.id || t.hidden)) {
      const shown = await windowWs(tab.windowId);
      await assign((await newTab(tab.windowId, shown)).id, shown);
    }
  }
  await browser.tabs.remove(tabId);
}

// -- containers -----------------------------------------------------------------------------------

const CONTAINER_ICONS = [
  "fingerprint", "briefcase", "dollar", "cart", "circle", "gift", "vacation", "food", "fruit", "pet", "tree", "chill",
  "fence",
];

// A new container: a colour no container has yet (while there is one), and the plain circle icon.
async function createContainer(msg) {
  const name = cleanName(msg.name);
  if (!name) return;
  const taken = new Set((await browser.contextualIdentities.query({})).map((c) => c.color));
  const color = COLORS.includes(msg.color) ? msg.color : COLORS.find((c) => !taken.has(c)) || COLORS[0];
  await browser.contextualIdentities.create({ name, color, icon: CONTAINER_ICONS.includes(msg.icon) ? msg.icon : "circle" });
}

// Its name, colour or icon, whichever the message names (and is valid).
async function updateContainer(msg) {
  const details = {};
  if (cleanName(msg.name)) details.name = cleanName(msg.name);
  if (COLORS.includes(msg.color)) details.color = msg.color;
  if (CONTAINER_ICONS.includes(msg.icon)) details.icon = msg.icon;
  if (Object.keys(details).length) await browser.contextualIdentities.update(msg.cookieStoreId, details);
}

// As Firefox's own settings do it: the container's tabs close first, then the container goes. The tabs close as
// the panel closes one (closeTab), so never with a window that holds other workspaces' hidden tabs; a workspace
// that opened its new tabs in this container stops first, or its replacement tab would open right in it.
async function removeContainer(store) {
  await browser.contextualIdentities.get(store); // (throws for what is not a container: nothing is closed)
  await forgetContainer(store);
  for (const tab of await browser.tabs.query({ cookieStoreId: store })) await closeTab(tab.id);
  await browser.contextualIdentities.remove(store);
}

// The keyboard shortcuts (manifest "commands", changeable in about:addons): the next or previous workspace,
// round the list, or the Nth.
async function onShortcut(name) {
  if (workspaces === null) return; // one workspace: nowhere to go
  const windowId = (await browser.windows.getLastFocused()).id;
  const shown = await windowWs(windowId);
  const at = workspaces.findIndex((w) => w.id === shown);
  const count = workspaces.length;
  const nth = /^workspace-([1-9])$/.exec(name);
  let to;
  if (name === "next-workspace") to = (at + 1) % count;
  else if (name === "previous-workspace") to = (at - 1 + count) % count;
  else if (nth) to = Number(nth[1]) - 1;
  if (to === undefined || to >= count || to === at) return;
  await switchWorkspace(windowId, workspaces[to].id);
}

// A tab left the window (closed, or dragged to another window). If it was the last one of the
// workspace the window shows, the browser has to pick one from another workspace: keep this one
// instead, with a new tab.
async function tabLeft(windowId) {
  if (workspaces === null) return;
  const shown = await windowWs(windowId);
  const tabs = await browser.tabs.query({ windowId });
  if (!tabs.length) return;
  for (const tab of tabs) {
    if (!tab.pinned && (await tabWsOf(tab)) === shown) return reconcile(windowId);
  }
  await focusWorkspace(windowId, shown);
  await reconcile(windowId);
}

async function onTabCreated(tab) {
  if (workspaces === null) {
    explicit.delete(tab.id);
    return;
  }
  const id = await tabWsOf(tab);
  if (await intoContainer(tab, id)) return;
  await reconcile(tab.windowId); // a tab reopened into another workspace (undo close) goes back there
}

// Tabs the panel opened in a container it was asked for ("No container" included): never taken over.
const explicit = new Set();

// A new tab on the new-tab page in no container, in a workspace with a container of its own, is reopened in
// that container, where the workspace opens its tabs (a tab cannot change its container). True if it was.
async function intoContainer(tab, id) {
  if (explicit.delete(tab.id) || tab.incognito || tab.pinned || tab.cookieStoreId !== "firefox-default") return false;
  if (!NEW_TAB_URLS.includes(tab.url)) return false;
  const store = await containerOf(id);
  if (store === null) return false;
  let fresh;
  try {
    fresh = await browser.tabs.create({ windowId: tab.windowId, index: tab.index, active: tab.active, cookieStoreId: store });
  } catch (e) {
    return false;
  }
  await assign(fresh.id, id);
  try {
    await browser.tabs.remove(tab.id);
  } catch (e) {
    // closed meanwhile
  }
  return true;
}

async function onTabRemoved(tabId, info) {
  tabWs.delete(tabId);
  explicit.delete(tabId);
  if (!info.isWindowClosing) await tabLeft(info.windowId);
}

async function onTabAttached(tabId, info) {
  if (workspaces === null) return;
  await assign(tabId, await windowWs(info.newWindowId)); // it joins what the window it was dropped in shows
  await reconcile(info.newWindowId);
}

async function onTabUnpinned(tabId) {
  const tab = await getTab(tabId);
  // it was in every workspace: now it belongs to the one you see it in
  if (workspaces !== null && tab !== null) await assign(tabId, await windowWs(tab.windowId));
}

// -- to the panel ---------------------------------------------------------------------------------

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
  const list = workspaces || [DEFAULT_WS];
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
    workspaces: list.map((w) => ({
      id: w.id,
      name: w.name,
      icon: w.icon || null,
      color: w.color || null,
      cookieStoreId: w.cookieStoreId || null,
    })),
    windows: windows.map((w) => {
      const shown = winWs.get(w.id) || list[0].id;
      return {
        id: w.id,
        focused: w.focused,
        workspaceId: shown,
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
          hidden: t.hidden,
          workspaceId: tabWs.get(t.id) || shown,
        })),
      };
    }),
  };
}

// Full snapshot on every change, debounced: simple and self-healing.
function push() {
  if (!port || !panelUp || pushTimer) return;
  pushTimer = setTimeout(async () => {
    pushTimer = null;
    try {
      send(await serial(snapshot)); // after the workspace changes queued so far
    } catch (e) {
      console.error("tabdock: snapshot failed", e);
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
      case "close_tab":
        if (Number.isInteger(msg.tabId)) await closeTab(msg.tabId);
        break;
      case "pin_tab":
        // tabs.onUpdated reports it; an unpinned tab joins the workspace its window shows
        if (Number.isInteger(msg.tabId)) await browser.tabs.update(msg.tabId, { pinned: msg.pinned === true });
        break;
      case "create_container":
        await createContainer(msg);
        break;
      case "update_container":
        if (typeof msg.cookieStoreId === "string") await updateContainer(msg);
        break;
      case "remove_container":
        if (typeof msg.cookieStoreId === "string") await removeContainer(msg.cookieStoreId);
        break;
      case "new_tab":
        // in the container asked for, even "No container" in a workspace that has one of its own
        explicit.add((await browser.tabs.create({ cookieStoreId: msg.cookieStoreId, windowId: msg.windowId })).id);
        break;
      case "switch_workspace":
        if (Number.isInteger(msg.windowId)) await switchWorkspace(msg.windowId, msg.workspaceId);
        push();
        break;
      case "new_workspace":
        if (Number.isInteger(msg.windowId)) await newWorkspace(msg.windowId, msg.name);
        push();
        break;
      case "rename_workspace":
        await renameWorkspace(msg.workspaceId, msg.name);
        push();
        break;
      case "edit_workspace":
        await editWorkspace(msg.workspaceId, msg);
        push();
        break;
      case "remove_workspace":
        await removeWorkspace(msg.workspaceId);
        push();
        break;
      case "move_tab_to_workspace":
        if (Number.isInteger(msg.tabId)) await moveToWorkspace(msg.tabId, msg.workspaceId);
        push();
        break;
      default:
        console.warn("tabdock: unknown command", msg.type);
    }
  } catch (e) {
    console.error("tabdock: command failed", msg, e);
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
    console.error("tabdock: connectNative failed", e);
    port = null;
    scheduleReconnect();
    return;
  }
  port.onMessage.addListener((msg) => serial(() => onCommand(msg)));
  port.onDisconnect.addListener((p) => {
    console.warn("tabdock: relay disconnected", p.error && p.error.message);
    port = null;
    panelUp = false;
    scheduleReconnect();
  });
}

// Workspace bookkeeping for a browser event, in turn with everything else, then a new snapshot.
function track(fn) {
  serial(fn).catch((e) => console.error("tabdock: workspace update failed", e));
  push();
}

browser.tabs.onCreated.addListener((tab) => track(() => onTabCreated(tab)));
browser.tabs.onRemoved.addListener((tabId, info) => track(() => onTabRemoved(tabId, info)));
browser.tabs.onMoved.addListener(push);
browser.tabs.onActivated.addListener((info) => track(() => reconcile(info.windowId)));
browser.tabs.onAttached.addListener((tabId, info) => track(() => onTabAttached(tabId, info)));
browser.tabs.onDetached.addListener((tabId, info) => track(() => tabLeft(info.oldWindowId)));
browser.tabs.onUpdated.addListener(push, {
  properties: ["title", "favIconUrl", "pinned", "audible", "discarded", "url", "hidden"],
});
browser.tabs.onUpdated.addListener(
  (tabId, change) => {
    if (change.pinned === false) track(() => onTabUnpinned(tabId));
  },
  { properties: ["pinned"] },
);
browser.windows.onCreated.addListener((w) => track(() => workspaces !== null && windowWs(w.id)));
browser.windows.onRemoved.addListener((windowId) => track(() => winWs.delete(windowId)));
browser.windows.onFocusChanged.addListener((id) => {
  // WINDOW_ID_NONE means focus left the browser: keep the last real window
  if (id !== browser.windows.WINDOW_ID_NONE) {
    lastFocusedWindowId = id;
    if (winWs.has(id)) lastWs = winWs.get(id);
  }
  push();
});
if (browser.contextualIdentities) {
  browser.contextualIdentities.onCreated.addListener(push);
  browser.contextualIdentities.onUpdated.addListener(push);
  browser.contextualIdentities.onRemoved.addListener((info) =>
    track(() => forgetContainer(info.contextualIdentity.cookieStoreId)),
  );
}
browser.commands.onCommand.addListener((name) => track(() => onShortcut(name)));

serial(loadWorkspaces).catch((e) => console.error("tabdock: loading workspaces failed", e));
connect();
