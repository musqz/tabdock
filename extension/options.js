"use strict";

const box = document.getElementById("bookmarks");
const perm = { permissions: ["bookmarks"] };

browser.permissions.contains(perm).then((granted) => (box.checked = granted));

// permissions.request needs the click: nothing is awaited before it
box.addEventListener("change", () => {
  const done = box.checked ? browser.permissions.request(perm) : browser.permissions.remove(perm);
  done.then(() => browser.permissions.contains(perm)).then((granted) => (box.checked = granted));
});
