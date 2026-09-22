/* Bluegrass Dry Ice — order builder, estimator, FAQ.
   Prices come from the server (window.BAGS, rendered by Flask from content.py). */

const BAGS = window.BAGS || [];
const qty = BAGS.map(() => 0);

let recommendedIndex = BAGS.length > 2 ? 2 : 0;

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------ toast */
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._hide);
  t._hide = setTimeout(() => t.classList.remove('show'), 3200);
}

/* ------------------------------------------------ order builder */
function changeQty(i, step) {
  qty[i] = Math.max(0, qty[i] + step);
  $('qty' + i).textContent = qty[i];
  updateSummary();
}

function selectedContainer() {
  const el = document.querySelector('input[name=container]:checked');
  return el ? Number(el.value) : 0;
}

function updateSummary() {
  const rows = BAGS
    .map((b, i) => qty[i]
      ? `<div class="sum-line"><span>${qty[i]} × ${b.name}</span><strong>$${qty[i] * b.price}</strong></div>`
      : '')
    .join('');

  $('summaryItems').innerHTML = rows ||
    '<p class="muted small" style="margin:0 0 8px">Choose a bag size to begin.</p>';

  const bagTotal = BAGS.reduce((sum, b, i) => sum + b.price * qty[i], 0);
  const container = selectedContainer();

  $('containerTotal').textContent = '$' + container;
  $('grandTotal').textContent = '$' + (bagTotal + container).toFixed(2);
}

document.querySelectorAll('[data-qty]').forEach((btn) => {
  btn.addEventListener('click', () =>
    changeQty(Number(btn.dataset.qty), Number(btn.dataset.step)));
});

document.querySelectorAll('input[name=container]').forEach((el) =>
  el.addEventListener('change', updateSummary));

/* ------------------------------------------------ checkout wizard steps */
let currentStep = 1;

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function goToStep(n) {
  currentStep = n;
  document.querySelectorAll('.checkout-step').forEach((el) => {
    el.hidden = Number(el.dataset.step) !== n;
  });
  document.querySelectorAll('.cstep').forEach((el) => {
    const s = Number(el.dataset.cstep);
    el.classList.toggle('active', s === n);
    el.classList.toggle('done', s < n);
  });
  if (n === 3) renderReview();
}

function renderReview() {
  const rows = BAGS
    .map((b, i) => qty[i] ? `<dt>${qty[i]} × ${escapeHtml(b.name)}</dt><dd>$${qty[i] * b.price}</dd>` : '')
    .join('');
  const containerEl = document.querySelector('input[name=container]:checked');
  const containerLabel = containerEl ? containerEl.closest('.opt').textContent.trim() : '—';
  const name = escapeHtml($('ckName').value || '—');
  const email = escapeHtml($('ckEmail').value || '—');
  const phone = escapeHtml($('ckPhone').value || '—');
  const date = escapeHtml($('ckDate').value || 'Not specified');
  const notes = escapeHtml($('ckNotes').value);

  $('reviewSummary').innerHTML =
    `<dl class="review-block">${rows || '<dt>Items</dt><dd>No bags selected</dd>'}` +
    `<dt>Container</dt><dd>${escapeHtml(containerLabel)}</dd></dl>` +
    `<dl class="review-block"><dt>Contact</dt><dd>${name} · ${email} · ${phone}</dd>` +
    `<dt>Preferred pickup date</dt><dd>${date}</dd>` +
    (notes ? `<dt>Notes</dt><dd>${notes}</dd>` : '') + `</dl>`;
}

document.querySelectorAll('[data-next]').forEach((btn) => {
  btn.addEventListener('click', () => {
    if (currentStep === 1) {
      const bagTotal = qty.reduce((sum, c) => sum + c, 0);
      if (bagTotal === 0) { toast('Choose at least one bag size first.'); return; }
    }
    if (currentStep === 2) {
      if (!$('ckName').value || !$('ckEmail').value || !$('ckPhone').value) {
        toast('Please fill in your name, email, and phone.');
        return;
      }
    }
    if (currentStep === 3 && document.querySelector('input[name=pay]:checked')?.value === 'online') {
      if (!$('billingLine1').value || !$('billingCity').value || !$('billingState').value || !$('billingZip').value) {
        toast('Please enter your billing address for online payment.');
        goToStep(4);
        return;
      }
    }
    goToStep(currentStep + 1);
  });
});

document.querySelectorAll('[data-back]').forEach((btn) => {
  btn.addEventListener('click', () => goToStep(currentStep - 1));
});

/* ------------------------------------------------ checkout (POST to Flask) */
async function checkout() {
  const items = {};
  qty.forEach((count, i) => { if (count) items[i] = count; });

  const payEl = document.querySelector('input[name=pay]:checked');
  const payload = {
    items,
    container: selectedContainer(),
    payment: payEl ? payEl.value : 'online',
    age: $('age').checked,
    airtight: $('airtight').checked,
    safety: $('safetyCheck').checked,
    name: $('ckName').value,
    email: $('ckEmail').value,
    phone: $('ckPhone').value,
    pickup_date: $('ckDate').value,
    notes: $('ckNotes').value,
    billing_line1: $('billingLine1').value,
    billing_line2: $('billingLine2').value,
    billing_city: $('billingCity').value,
    billing_state: $('billingState').value,
    billing_zip: $('billingZip').value,
    save_billing: $('saveBilling').checked
  };

  const btn = $('checkoutBtn');
  btn.disabled = true;

  try {
    const res = await fetch('/api/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      if (res.status === 401) {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + '#order');
        return;
      }
      toast(data.error || 'Something went wrong. Please try again.');
      return;
    }

    if (data.checkout_url) {
      window.location.href = data.checkout_url;
      return;
    }

    toast(data.message);
    const notice = $('orderNotice');
    notice.classList.add('ok');
    notice.textContent =
      `Reserved ${data.order.id} · ${data.order.total_lbs} lb · ` +
      `$${data.order.total.toFixed(2)} (${data.order.payment === 'online' ? 'pay online' : 'pay at pickup'}).`;
  } catch (err) {
    toast('Could not reach the server. Is the Flask app running?');
  } finally {
    btn.disabled = false;
  }
}

$('checkoutBtn').addEventListener('click', checkout);

/* ------------------------------------------------ estimator (POST to Flask) */
async function calculateNeed() {
  const payload = {
    use: $('calcUse').value,
    days: Number($('calcDays').value),
    size: Number($('calcSize').value)
  };

  try {
    const res = await fetch('/api/estimate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'estimate failed');

    $('recRange').textContent = data.range_label;
    $('recCopy').textContent = data.copy;
    $('recBagLabel').textContent = data.bag.name;
    recommendedIndex = BAGS.findIndex((b) => b.name === data.bag.name);
    if (recommendedIndex < 0) recommendedIndex = BAGS.length - 1;
  } catch (err) {
    toast('Could not calculate right now. Please try again.');
  }
}

function orderRecommendation() {
  changeQty(recommendedIndex, 1);
  goToStep(1);
  $('order').scrollIntoView({ behavior: 'smooth' });
  toast(BAGS[recommendedIndex].name + ' added to your order.');
}

$('estimateBtn').addEventListener('click', calculateNeed);
$('addRecBtn').addEventListener('click', orderRecommendation);

/* ------------------------------------------------ faq */
document.querySelectorAll('.faq-q').forEach((q) =>
  q.addEventListener('click', () => q.parentElement.classList.toggle('open')));

/* ------------------------------------------------ init */
calculateNeed();
updateSummary();
