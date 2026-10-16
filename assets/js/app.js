/* =============================================================================
   Shopcart — shared frontend logic
   =============================================================================
   What lives here:
     • Server catalog sync        – names/prices/STOCK come from /api/catalog
     • Icon set (inline SVG)      – stars, heart, cart, etc.
     • Cart state                 – localStorage persisted, server-validated
     • Toast notifications        – small confirmation banners
     • Product card renderer      – grid cards with stock + OOS states
     • Dropdown menus             – filter / sort pills
     • Mobile navigation          – hamburger drawer
   All money maths shown in the UI is advisory — the SERVER recomputes
   everything authoritatively at order time.
   ========================================================================== */

/* ---------------------------------------------------------------------------
   Icon set (inline SVG strings, referenced by every renderer below)
--------------------------------------------------------------------------- */
const ICONS = {
  star:     `<svg class="icon" viewBox="0 0 24 24" fill="#0AAD0A"><path d="M12 2l2.94 6.26 6.86.83-5.06 4.7 1.34 6.74L12 17.27l-6.08 3.26 1.34-6.74-5.06-4.7 6.86-.83z"/></svg>`,
  starHalf: `<svg class="icon" viewBox="0 0 24 24"><defs><linearGradient id="halfStar"><stop offset="50%" stop-color="#0AAD0A"/><stop offset="50%" stop-color="#E2E5E4"/></linearGradient></defs><path fill="url(#halfStar)" d="M12 2l2.94 6.26 6.86.83-5.06 4.7 1.34 6.74L12 17.27l-6.08 3.26 1.34-6.74-5.06-4.7 6.86-.83z"/></svg>`,
  starDim:  `<svg class="icon" viewBox="0 0 24 24" fill="#E2E5E4"><path d="M12 2l2.94 6.26 6.86.83-5.06 4.7 1.34 6.74L12 17.27l-6.08 3.26 1.34-6.74-5.06-4.7 6.86-.83z"/></svg>`,
  heart:    `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>`,
  check:    `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`,
  trash:    `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14z"/></svg>`,
  warn:     `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0z"/></svg>`,
};

/** Render `rating` (e.g. 4.5) as 5 star SVGs. */
function stars(rating){
  let h = "";
  for (let i = 1; i <= 5; i++)
    h += rating >= i ? ICONS.star : rating >= i - .5 ? ICONS.starHalf : ICONS.starDim;
  return h;
}

/* Number/price formatters (display only — server owns the real maths). */
const fmt = n => n.toFixed(2);
const priceHTML = n => `<span class="price"><sup>$</sup>${fmt(n)}</span>`;

/* ---------------------------------------------------------------------------
   Server catalog sync
--------------------------------------------------------------------------- */
let CATALOG = {};                       // filled from /api/catalog at boot
let CATALOG_READY = false;

/** Pull live products (incl. availability) from the server. */
async function syncCatalog(){
  try {
    const r = await fetch("/api/catalog");
    CATALOG = await r.json();
  } catch (e) {
    console.warn("catalog sync failed, page may be offline", e);
    CATALOG = {};
  }
  CATALOG_READY = true;
  document.dispatchEvent(new CustomEvent("catalog:ready"));   // pages listen
}

/** Home-grid display order (matches the design). */
const GRID_ORDER = ["earbuds-ipx8","airpods-max","bose-bt","vivefox",
                    "jbl-600","tagry","monster","mpow"];

/** Units the customer may still buy (stock minus server-side reservations). */
const available = id => (CATALOG[id] ? CATALOG[id].available ?? 0 : 0);

/* ---------------------------------------------------------------------------
   Cart state — persisted in localStorage so it survives navigation/reloads.
   Shape: [{id, qty}]. The server re-validates it on the cart page and at
   checkout, so stale lines can never silently purchase.
--------------------------------------------------------------------------- */
const CART_KEY = "shopcart_cart";
const WISH_KEY = "shopcart_wish";
const ORDERS_KEY = "shopcart_orders";   // mini order-history for receipt links

const getCart  = () => { try { return JSON.parse(localStorage.getItem(CART_KEY)) || []; } catch { return []; } };
const setCart  = c => { localStorage.setItem(CART_KEY, JSON.stringify(c)); updateBadge(); };
const getWish  = () => { try { return JSON.parse(localStorage.getItem(WISH_KEY)) || []; } catch { return []; } };
const setWish  = w => localStorage.setItem(WISH_KEY, JSON.stringify(w));
const clearCart = () => setCart([]);

const cartCount = () => getCart().reduce((s, i) => s + i.qty, 0);
const cartTotal = () => getCart().reduce((s, i) =>
    s + (CATALOG[i.id] ? CATALOG[i.id].price * i.qty : 0), 0);

/** Remember a paid order locally (id + receipt link + total) for the history. */
function rememberOrder(o){
  const list = JSON.parse(localStorage.getItem(ORDERS_KEY) || "[]");
  list.unshift({ id: o.id, reference: o.reference, total: o.total,
                 receiptUrl: o.receiptUrl, date: o.paid || o.created,
                 method: o.method, status: o.status });
  localStorage.setItem(ORDERS_KEY, JSON.stringify(list.slice(0, 20)));
}

/** Refresh every navbar cart badge on the page. */
function updateBadge(){
  document.querySelectorAll(".cart-badge").forEach(b => {
    const n = cartCount();
    b.textContent = n > 0 ? (n > 99 ? "99+" : n) : "";
    b.classList.toggle("hide", n === 0);
  });
}

/**
 * Add `qty` of product `id` to the cart — with a HARD cap at the server's
 * available stock. Never lets the basket exceed what can be bought.
 * @returns true when the full requested qty was added.
 */
function addToCart(id, qty = 1){
  const p = CATALOG[id];
  if (!p) return false;
  if (available(id) <= 0){                       // completely sold out
    toast(`${p.name} is out of stock`, "warn");
    return false;
  }
  const cart = getCart();
  const line = cart.find(l => l.id === id) || { id, qty: 0 };
  const room = available(id) - line.qty;         // how many more fit
  if (room <= 0){
    toast(`Only ${available(id)} × ${p.name} available`, "warn");
    return false;
  }
  const added = Math.min(qty, room);
  line.qty += added;
  if (!cart.includes(line)) cart.push(line);
  setCart(cart);
  toast(added < qty
    ? `Added ${added} — only ${available(id)} in stock`
    : `${p.name} added to cart`);
  refreshCardButtons(id);
  return added === qty;
}

/** Set an item's qty directly (cart page steppers) — clamped to stock ≥ 0. */
function setLineQty(id, qty){
  let cart = getCart();
  qty = Math.min(qty, available(id));            // hard stock ceiling
  if (qty <= 0) cart = cart.filter(l => l.id !== id);
  else cart.find(l => l.id === id).qty = qty;
  setCart(cart);
}

/** Visual state of every "Add to Cart" button for one product. */
function refreshCardButtons(id){
  const inCart = getCart().find(l => l.id === id);
  document.querySelectorAll(`[data-add="${id}"]`).forEach(b => {
    const oos = available(id) <= 0;
    b.disabled = oos;
    b.classList.toggle("in-cart", !!inCart && !oos);
    b.textContent = oos ? "Out of Stock" : inCart ? "In Cart ✓" : "Add to Cart";
  });
}

/* ---------------------------------------------------------------------------
   Toast notifications
--------------------------------------------------------------------------- */
function toast(msg, kind = "ok"){
  let t = document.querySelector(".toast");
  if (!t){ t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
  t.classList.toggle("warn", kind === "warn");
  t.innerHTML = (kind === "warn" ? ICONS.warn : ICONS.check) + `<span>${msg}</span>`;
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 2400);
}

/* ---------------------------------------------------------------------------
   Product card renderer (used by home grid, similar/recently sections)
--------------------------------------------------------------------------- */
function cardHTML(id){
  const p = CATALOG[id];
  if (!p) return "";
  const oos   = available(id) <= 0;
  const low   = !oos && available(id) <= 5;             // "only X left" hint
  const wish  = getWish().includes(id) ? " active" : "";
  const line  = getCart().find(l => l.id === id);
  return `
  <article class="pcard" data-id="${id}">
    <a class="thumb" href="product.html?id=${id}" aria-label="${p.name}">
      <img src="${p.img}" alt="${p.name}" loading="lazy">
      ${oos  ? `<span class="badge oos">Out of Stock</span>` : ""}
      ${low  ? `<span class="badge low">Only ${available(id)} left</span>` : ""}
    </a>
    <button class="wish${wish}" data-wish="${id}" aria-label="Add to wishlist">${ICONS.heart}</button>
    <div class="body">
      <div class="row1">
        <h4><a href="product.html?id=${id}">${p.name}</a></h4>
        ${priceHTML(p.price)}
      </div>
      <p class="desc">${p.desc}</p>
      <div class="rate">${stars(p.rating)}<span class="n">(121)</span></div>
      <button class="add ${line && !oos ? "in-cart" : ""}" data-add="${id}" ${oos ? "disabled" : ""}>
        ${oos ? "Out of Stock" : line ? "In Cart ✓" : "Add to Cart"}
      </button>
    </div>
  </article>`;
}

/** Wire wishlist + add-to-cart buttons inside `scope`. */
function bindCards(scope = document){
  scope.querySelectorAll("[data-wish]").forEach(btn => btn.onclick = e => {
    e.preventDefault();
    const id = btn.dataset.wish, w = getWish(), i = w.indexOf(id);
    if (i >= 0){ w.splice(i, 1); btn.classList.remove("active"); }
    else { w.push(id); btn.classList.add("active"); toast(`${CATALOG[id].name} saved to wishlist`); }
    setWish(w);
  });
  scope.querySelectorAll("[data-add]").forEach(btn => btn.onclick = e => {
    e.preventDefault();
    addToCart(btn.dataset.add);
  });
}

/* ---------------------------------------------------------------------------
   Dropdown menus (filter pills / sort)
--------------------------------------------------------------------------- */
function makeMenu(anchorBtn, options, onPick){
  const m = document.createElement("div");
  m.className = "fmenu";
  m.innerHTML = options.map((o, i) => `<button data-i="${i}">${o}</button>`).join("");
  anchorBtn.parentElement.appendChild(m);
  anchorBtn.addEventListener("click", e => {
    e.stopPropagation();
    document.querySelectorAll(".fmenu.open").forEach(x => { if (x !== m) x.classList.remove("open"); });
    m.style.left = Math.max(0, Math.min(anchorBtn.offsetLeft,
                     window.innerWidth - 230)) + "px";       // keep on-screen
    m.classList.toggle("open");
  });
  m.querySelectorAll("button").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation();
    onPick(b.textContent.trim(), +b.dataset.i, m);
    m.classList.remove("open");
  }));
  document.addEventListener("click", () => m.classList.remove("open"));
  return m;
}

/* ---------------------------------------------------------------------------
   Mobile navigation — hamburger button toggles a slide-in drawer containing
   the nav links + search (their desktop versions are hidden by CSS).
--------------------------------------------------------------------------- */
function initMobileNav(){
  const burger = document.querySelector(".burger");
  const drawer = document.querySelector(".drawer");
  if (!burger || !drawer) return;
  burger.addEventListener("click", () => {
    const open = drawer.classList.toggle("open");
    burger.classList.toggle("open", open);
    burger.setAttribute("aria-expanded", open);
    document.body.classList.toggle("no-scroll", open);
  });
  drawer.querySelectorAll("a").forEach(a =>
    a.addEventListener("click", () => {
      drawer.classList.remove("open");
      burger.classList.remove("open");
      document.body.classList.remove("no-scroll");
    }));
}

/* ---------------------------------------------------------------------------
   Boot — shared by every page: inject badge, sync catalog, wire chrome.
--------------------------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  const cartLink = document.querySelector(".cartlink");
  if (cartLink && !cartLink.querySelector(".cart-badge")){
    const b = document.createElement("span");
    b.className = "cart-badge hide";
    cartLink.appendChild(b);
  }
  updateBadge();
  initMobileNav();
  syncCatalog().then(() => { updateBadge(); });
});
