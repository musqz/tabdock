"use strict";

for (const box of document.querySelectorAll("input[data-permission]")) {
  const perm = { permissions: [box.dataset.permission] };
  browser.permissions.contains(perm).then((granted) => (box.checked = granted));

  // permissions.request needs the click: nothing is awaited before it
  box.addEventListener("change", () => {
    const done = box.checked ? browser.permissions.request(perm) : browser.permissions.remove(perm);
    done
      .catch(() => {})
      .then(() => browser.permissions.contains(perm))
      .then((granted) => (box.checked = granted));
  });
}
