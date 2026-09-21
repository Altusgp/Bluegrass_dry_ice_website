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
    safety: $('safetyCheck').checked
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
      toast(data.error || 'Something went wrong. Please try again.');
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
