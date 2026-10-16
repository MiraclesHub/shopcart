/* =============================================================================
   Shopcart — checkout & payment orchestrator
   =============================================================================
   Flow (all amounts are computed SERVER-SIDE; this file only orchestrates):

     cart ──► POST /api/orders          create PENDING order + reserve stock
          ──► POST /api/payments/init   method-specific instructions
          ──► pay (card / bank / crypto / pod)
          ──► GET  /api/payments/verify authoritative status
          ──► paid → clear cart, remember order, show receipt

   CARD SECURITY MODEL
   • PRODUCTION (Paystack): the card form is NEVER used — checkout opens
     Paystack's PCI-DSS-certified hosted popup (PaystackPop) or redirect,
     so raw card data only ever travels browser ⇆ Paystack.
   • DEMO mode: the local form validates format + tokenises the card
     (SHA-256 of PAN|exp|cvc|reference) and sends ONLY
     {network, last4, token} to the server. The full number and CVC are
     discarded in-memory and never transmitted or stored.
   ========================================================================== */

"use strict";

/* ---------------------------------------------------------------------------
   Small DOM helpers
--------------------------------------------------------------------------- */
const $  = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

let CFG = null;            // /api/config response (mode, keys, assets, methods)
let ORDER = null;          // current pending order (server object)
let PAY = null;            // payments/init payload for the current method

/* ---------------------------------------------------------------------------
   Boot: load runtime config + live catalog, then render order review
--------------------------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", async () => {
  try { CFG = await (await fetch("/api/config")).json(); }
  catch { CFG = { mode: "demo", methods: ["card", "bank", "crypto", "pod"] }; }

  if (CFG.mode === "demo"){                       // label the sandbox clearly
    $("#demoRibbon").style.display = "block";
    $("#cardModeNote").textContent = "Demo card gateway — nothing is charged";
  }

  const start = () => { renderReview(); totalsLocal(); initTabs(); initForms(); };
  if (CATALOG_READY) start();
  else document.addEventListener("catalog:ready", start, { once: true });

  $("#succHome").onclick = () => location.href = "index.html";
});

/* ---------------------------------------------------------------------------
   Order review panel + totals (display maths; server re-prices at order time)
--------------------------------------------------------------------------- */
function renderReview(){
  const wrap = $("#coItems");
  const cart = getCart();
  if (!cart.length){
    wrap.innerHTML = `<p style="margin-top:20px;color:var(--muted);font-size:14px">
      No items yet — <a href="index.html" style="text-decoration:underline;
      color:var(--green);font-weight:600">continue shopping</a>.</p>`;
    disableAllPay();
    return;
  }
  wrap.innerHTML = cart.map(l => {
    const p = CATALOG[l.id]; if (!p) return "";
    return `
    <div class="co-item">
      <a class="thumb" href="product.html?id=${l.id}"><img src="${p.img}" alt="${p.name}"></a>
      <div><h4>${p.name}</h4><p class="meta">Color: ${p.id === "airpods-max" ? "Pink" : "Default"}</p></div>
      <div class="right"><span class="p">$${fmt(p.price * l.qty)}</span>
        <p class="q">Quantity: ${String(l.qty).padStart(2, "0")}</p></div>
    </div>`;
  }).join("");
}

function couponCode(){ return (sessionStorage.getItem("sc_coupon") || "").toUpperCase(); }

function totalsLocal(){
  const sub  = cartTotal();
  const disc = couponCode() === "SHOP10" ? sub * .10 : 0;
  $("#coSub").textContent = "$" + fmt(sub);
  $("#coDiscRow").style.display = disc ? "flex" : "none";
  $("#coDisc").textContent = "–$" + fmt(disc);
  $("#coTotal").textContent = "$" + fmt(sub - disc);
}

$("#coApply") && ($("#coApply").onclick = () => {
  const v = $("#coCoupon").value.trim().toUpperCase();
  if (v === "SHOP10"){ sessionStorage.setItem("sc_coupon", "SHOP10"); toast("Coupon applied — 10% off"); }
  else if (v){ sessionStorage.removeItem("sc_coupon"); toast("Invalid coupon code", "warn"); }
  totalsLocal();
});

/* ---------------------------------------------------------------------------
   Delivery information — view ⇄ inline edit
--------------------------------------------------------------------------- */
(function initDeliveryInfo(){
  const btn = $("#editInfo");
  if (!btn) return;
  let editing = false;
  btn.addEventListener("click", () => {
    const dds = $$("#infoGrid dd");
    if (!editing){                                    // turn values into inputs
      dds.forEach(dd => dd.innerHTML =
        `<input type="text" value="${dd.textContent.replace(/"/g, "&quot;")}">`);
      btn.textContent = "Save Information";
      editing = true;
    } else {                                          // persist + back to view
      dds.forEach(dd => {
        const v = dd.querySelector("input").value.trim();
        dd.textContent = v || dd.querySelector("input").defaultValue;
      });
      toast("Delivery information updated");
      btn.textContent = "Edit Information";
      editing = false;
    }
  });
})();

/* ---------------------------------------------------------------------------
   Payment-method tabs
--------------------------------------------------------------------------- */
let METHOD = "card";
function initTabs(){
  $$("#paytabs .paytab").forEach(tab => tab.onclick = () => {
    $$("#paytabs .paytab").forEach(t => t.classList.toggle("active", t === tab));
    METHOD = tab.dataset.m;
    $$(".paypane").forEach(p =>
      p.classList.toggle("active", p.dataset.pane === METHOD));
    $("#cardPay").style.display = METHOD === "card" ? "" : "none";
    hideError();
  });
  $("#cardPay").style.display = "";
}

/* ---------------------------------------------------------------------------
   Card detection & validation helpers
--------------------------------------------------------------------------- */
/** Identify the card network from its number (BIN prefixes incl. Verve). */
function detectNetwork(num){
  const n = num.replace(/\D/g, "");
  if (/^(5060|5061|5078|6500)/.test(n)) return "verve";       // Verve (NG)
  if (/^4/.test(n))                    return "visa";
  if (/^(5[1-5]|2[2-7])/.test(n))      return "mastercard";   // incl. 2-series
  if (/^3[47]/.test(n))                return "amex";
  if (/^6(011|5|4[4-9])/.test(n))      return "discover";
  if (/^62/.test(n))                   return "unionpay";
  if (/^35/.test(n))                   return "jcb";
  return "";
}

/** Luhn checksum — catches typos before any network call. */
function luhn(num){
  const d = num.replace(/\D/g, "");
  if (d.length < 12) return false;
  let sum = 0, alt = false;
  for (let i = d.length - 1; i >= 0; i--){
    let n = +d[i];
    if (alt){ n *= 2; if (n > 9) n -= 9; }
    sum += n; alt = !alt;
  }
  return sum % 10 === 0;
}

const digits = v => v.replace(/\D/g, "");

function setValidity(input, ok, hint){
  input.classList.toggle("invalid", !ok);
  if (hint) hint.classList.toggle("show", !ok);
}

/* Card-number live behaviour: grouped formatting + network badge. */
function initForms(){
  const num = $("#cardNum"), badge = $("#netBadge");

  num.addEventListener("input", () => {
    const net = detectNetwork(num.value);
    let v = digits(num.value).slice(0, net === "amex" ? 15 : 16);
    /* 4-4-4-4 grouping (Amex 4-6-5) */
    num.value = net === "amex"
      ? v.replace(/(\d{4})(\d{0,6})(\d{0,5})/, (m, a, b, c) => [a, b, c].filter(Boolean).join(" "))
      : v.replace(/(\d{4})(?=\d)/g, "$1 ");
    badge.textContent = (net || "card").toUpperCase();
    badge.className = "netbadge " + net;
    setValidity(num, true, $("#numHint"));
  });

  $("#cardExp").addEventListener("input", e => {
    let v = digits(e.target.value).slice(0, 4);
    if (v.length >= 3) v = v.slice(0, 2) + "/" + v.slice(2);
    e.target.value = v;
    setValidity(e.target, true, $("#expHint"));
  });

  $("#cardCvc").addEventListener("input", e => {
    e.target.value = digits(e.target.value).slice(0, 4);
    setValidity(e.target, true, $("#cvcHint"));
  });

  $("#cardName").addEventListener("input", e =>
    setValidity(e.target, true, $("#nameHint")));

  $("#cardPay").onclick = payWithCard;
  $("#bankGetAcct").onclick = initBank;
  $("#bankConfirm").onclick = confirmBank;
  $("#cryptoGetAddr").onclick = initCrypto;
  $("#cryptoConfirm").onclick = confirmCrypto;
  $("#podPlace").onclick = placePod;
}

/** Full client-side card check. Returns {pan, exp, cvc, network} or null. */
function validateCard(){
  const pan = digits($("#cardNum").value);
  const net = detectNetwork(pan);
  const okNum = pan.length >= 13 && luhn(pan) && !!net;
  setValidity($("#cardNum"), okNum, $("#numHint"));

  const m = $("#cardExp").value.match(/^(\d{2})\/(\d{2})$/);
  let okExp = false;
  if (m){
    const mm = +m[1], yy = 2000 + +m[2];
    const now = new Date();
    okExp = mm >= 1 && mm <= 12 &&
            (yy > now.getFullYear() || (yy === now.getFullYear() && mm >= now.getMonth() + 1));
  }
  setValidity($("#cardExp"), okExp, $("#expHint"));

  const cvc = digits($("#cardCvc").value);
  const okCvc = net === "amex" ? cvc.length === 4 : cvc.length === 3;
  setValidity($("#cardCvc"), okCvc, $("#cvcHint"));

  const okName = $("#cardName").value.trim().length >= 2;
  setValidity($("#cardName"), okName, $("#nameHint"));

  return (okNum && okExp && okCvc && okName)
    ? { pan, exp: $("#cardExp").value, cvc, network: net } : null;
}

/* ---------------------------------------------------------------------------
   Order creation (shared by every method)
--------------------------------------------------------------------------- */
async function ensureOrder(){
  const email = ($("#infoGrid dd[data-k=email]").textContent || "").trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)){
    showError("Please set a valid email in Delivery Information (needed for your receipt).");
    $("#infoGrid dd[data-k=email]").scrollIntoView({ behavior: "smooth", block: "center" });
    return null;
  }
  const r = await fetch("/api/orders", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lines: getCart(), coupon: couponCode(),
                           email, method: METHOD }) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok){ showError(data.error || "Could not create your order."); return null; }
  ORDER = data;
  return ORDER;
}

function disableAllPay(){
  ["cardPay", "bankGetAcct", "cryptoGetAddr", "podPlace"].forEach(id => {
    const el = $("#" + id); if (el) el.disabled = true;
  });
}

/* ---------------------------------------------------------------------------
   1) CARD PAYMENT
--------------------------------------------------------------------------- */
async function payWithCard(){
  hideError();
  const card = validateCard();
  if (!card) return;

  const btn = $("#cardPay"); setBusy(btn, true);
  try {
    if (!(ORDER && ORDER.status === "pending") && !(await ensureOrder())) return;

    const init = await (await fetch("/api/payments/init", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orderId: ORDER.id }) })).json();

    /* —— PRODUCTION: Paystack hosted popup (card data never touches us) —— */
    if (init.gateway === "paystack"){
      if (typeof PaystackPop === "undefined"){
        location.href = init.authorizationUrl;           // redirect fallback
        return;
      }
      PaystackPop.setup({
        key: init.publicKey, email: ORDER.email,
        amount: Math.round(ORDER.total * 100), currency: ORDER.currency,
        ref: init.reference,
        onClose: () => fetch("/api/payments/cancel", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ orderId: ORDER.id }) }),
        callback: () => finalize(init.reference),        // then verify server-side
      }).openIframe();
      return;
    }

    /* —— DEMO gateway: tokenise locally, send metadata only —— */
    const token = await sha256(
      `${card.pan}|${card.exp}|${card.cvc}|${init.reference}`);
    const res = await (await fetch("/api/payments/demo-card-pay", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference: init.reference, network: card.network,
                             last4: card.pan.slice(-4), token,
                             email: ORDER.email }) })).json();

    /* scrub sensitive fields immediately (defence in depth) */
    card.pan = card.cvc = "";
    $("#cardNum").value = $("#cardCvc").value = "";

    if (res.status === "paid") onPaid(res.order);
    else showError(res.message || "Payment failed. Please try another card.");
  } catch (e){
    showError("Network error while processing payment. Please retry.");
  } finally {
    setBusy(btn, false);
  }
}

/* ---------------------------------------------------------------------------
   2) BANK TRANSFER
--------------------------------------------------------------------------- */
async function initBank(){
  hideError();
  const btn = $("#bankGetAcct"); setBusy(btn, true);
  try {
    if (!(ORDER && ORDER.status === "pending") && !(await ensureOrder())) return;
    PAY = await (await fetch("/api/payments/init", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orderId: ORDER.id }) })).json();
    $("#bankInstr").innerHTML = `
      <div class="r"><span>Bank</span><b>${PAY.bank}</b></div>
      <div class="r"><span>Account Number</span><b>${PAY.account}
        <button class="copybtn" data-copy="${PAY.account}">Copy</button></b></div>
      <div class="r"><span>Amount</span><b>$${fmt(PAY.amount)} ${PAY.currency}</b></div>
      <div class="r"><span>Reference</span><b class="addr">${PAY.reference}
        <button class="copybtn" data-copy="${PAY.reference}">Copy</button></b></div>`;
    $("#bankInstr").style.display = "block";
    $("#bankConfirm").style.display = "";
    btn.style.display = "none";
    wireCopy();
    toast("Transfer details generated");
  } finally { setBusy(btn, false); }
}

async function confirmBank(){
  hideError();
  const sender = $("#bankSender").value.trim();
  if (sender.length < 2){ setValidity($("#bankSender"), false, $("#senderHint")); return; }
  setValidity($("#bankSender"), true, $("#senderHint"));
  const btn = $("#bankConfirm"); setBusy(btn, true);
  try {
    const res = await (await fetch("/api/payments/manual-confirm", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference: PAY.reference, kind: "bank",
                             detail: { sender } }) })).json();
    if (res.status === "paid") onPaid(res.order);
    else showError("Transfer not confirmed yet — please retry in a moment.");
  } finally { setBusy(btn, false); }
}

/* ---------------------------------------------------------------------------
   3) CRYPTO
--------------------------------------------------------------------------- */
async function initCrypto(){
  hideError();
  const asset = $("#cryptoAssets .active").dataset.asset;
  const btn = $("#cryptoGetAddr"); setBusy(btn, true);
  try {
    if (!(ORDER && ORDER.status === "pending") && !(await ensureOrder())) return;
    PAY = await (await fetch("/api/payments/init", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orderId: ORDER.id, asset }) })).json();
    $("#cryptoInstr").innerHTML = `
      <div class="r"><span>Asset</span><b>${PAY.asset} (${PAY.network})</b></div>
      <div class="r"><span>Amount</span><b>$${fmt(PAY.amount)} ${PAY.currency} equiv.</b></div>
      <div class="r"><span>Deposit Address</span><b class="addr">${PAY.address}
        <button class="copybtn" data-copy="${PAY.address}">Copy</button></b></div>
      <div class="r"><span>Memo / Reference</span><b class="addr">${PAY.reference}</b></div>`;
    $("#cryptoInstr").style.display = "block";
    $("#cryptoConfirm").style.display = "";
    btn.style.display = "none";
    wireCopy();
  } finally { setBusy(btn, false); }
}

/* asset switch resets the generated address */
$("#cryptoAssets") && $$("#cryptoAssets button").forEach(b => b.onclick = () => {
  $$("#cryptoAssets button").forEach(x => x.classList.toggle("active", x === b));
  $("#cryptoInstr").style.display = "none";
  $("#cryptoConfirm").style.display = "none";
  $("#cryptoGetAddr").style.display = "";
});

async function confirmCrypto(){
  hideError();
  const txhash = $("#cryptoTx").value.trim();
  if (txhash.length < 10){ setValidity($("#cryptoTx"), false, $("#txHint")); return; }
  setValidity($("#cryptoTx"), true, $("#txHint"));
  const btn = $("#cryptoConfirm"); setBusy(btn, true);
  try {
    const res = await (await fetch("/api/payments/manual-confirm", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference: PAY.reference, kind: "crypto",
                             detail: { txhash, asset: PAY.asset } }) })).json();
    if (res.status === "paid") onPaid(res.order);
    else showError("Could not confirm the transaction yet — try again shortly.");
  } finally { setBusy(btn, false); }
}

/* ---------------------------------------------------------------------------
   4) PAY ON DELIVERY
--------------------------------------------------------------------------- */
async function placePod(){
  hideError();
  const btn = $("#podPlace"); setBusy(btn, true);
  try {
    if (!(ORDER && ORDER.status === "pending") && !(await ensureOrder())) return;
    /* /api/orders already marked POD orders as 'placed' */
    if (ORDER.status === "placed") onPaid(ORDER, {
      title: "Order Placed!",
      text: "Your order is confirmed — pay cash or POS when it arrives." });
    else showError("Could not place the order. Please retry.");
  } finally { setBusy(btn, false); }
}

/* ---------------------------------------------------------------------------
   Post-payment: authoritative verify → success UI → clear cart → receipt
--------------------------------------------------------------------------- */
async function finalize(reference){
  const r = await (await fetch(`/api/payments/verify/${reference}`)).json();
  if (r.status === "paid") onPaid(r.order);
  else showError("Payment is not confirmed yet. If you were charged, contact support.");
}

function onPaid(order, { title = "Payment Successful!",
    text = "Your payment has been confirmed and your order is being prepared." } = {}){
  clearCart();                                 // purchased items leave the basket
  sessionStorage.removeItem("sc_coupon");
  rememberOrder(order);                        // local order history (receipt link)
  $("#succTitle").textContent = title;
  $("#succText").textContent = text;
  $("#succOrder").textContent = order.id;
  $("#succTotal").textContent = "$" + fmt(order.total) + " " + order.currency;
  $("#succReceipt").href = order.receiptUrl;   // tokenised server receipt
  $("#successOverlay").classList.add("show");
  renderReview();                              // review panel now shows empty cart
  totalsLocal();
}

/* ---------------------------------------------------------------------------
   UI utilities
--------------------------------------------------------------------------- */
function wireCopy(){
  $$(".copybtn").forEach(b => b.onclick = () => {
    navigator.clipboard && navigator.clipboard.writeText(b.dataset.copy);
    toast("Copied to clipboard");
  });
}

/** SHA-256 hex (WebCrypto) — used for the demo payment token. */
async function sha256(str){
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function setBusy(btn, busy){
  btn.classList.toggle("busy", busy);
  btn.disabled = busy;
}

function showError(msg){
  const e = $("#payErr");
  e.textContent = msg;
  e.style.display = "block";
  e.scrollIntoView({ behavior: "smooth", block: "center" });
}
function hideError(){ $("#payErr").style.display = "none"; }
