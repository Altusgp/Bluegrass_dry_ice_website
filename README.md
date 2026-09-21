# Bluegrass Dry Ice — website

Flask + HTML/CSS/JS site for local dry ice pickup in Nicholasville / Lexington, KY.

## Run

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000

## Layout

```
app.py                  Flask routes + estimator/order API
content.py              All catalog + copy (prices, hours, FAQs, use cases)
templates/index.html    Page markup (Jinja)
static/css/styles.css   Styles
static/js/main.js       Order builder, estimator, FAQ accordion
static/images/          Use-case card photos (see below)
```

## API

| Endpoint        | Method | Purpose                                                     |
|-----------------|--------|-------------------------------------------------------------|
| `/`             | GET    | Renders the page                                             |
| `/api/estimate` | POST   | `{use, days, size}` → recommended lb range + closest bag     |
| `/api/orders`   | GET    | Orders taken this run (prototype, in memory)                 |
| `/api/order`    | POST   | Validates the cart, returns an order id and total            |

## Use-case card photos

The "Reliable Supply. Premium Quality." cards show a photo above the text.
Drop JPGs into `static/images/` with these names and they appear automatically —
until then each card falls back to a colored gradient:

`food-beverage.jpg`, `shipping-transport.jpg`, `emergency-cooling.jpg`,
`camping-outdoors.jpg`, `events-effects.jpg`, `science-labs.jpg`,
`industrial-maintenance.jpg`, `agriculture-specialty.jpg`

Recommended size: about 640 × 420 px.

## Before launch

- Replace the in-memory `ORDERS` dict with a real database.
- Connect Stripe or Square in `/api/order` for live payments.
- Hook up SMS/email confirmations.
- Confirm published hours, ZIP code, and the pickup entrance wording.
