import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as site


class PickupOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = patch.multiple(site, DB_BACKEND="sqlite", SQLITE_PATH=str(Path(self.temp.name) / "test.db"))
        self.config.start()
        site.app.config.update(TESTING=True, SECRET_KEY="test-only")
        self.client = site.app.test_client()
        with site.app.app_context():
            site.init_db()
            site.query_db("INSERT INTO users (name,email,phone,password_hash,created_at) VALUES (%s,%s,%s,%s,%s)",
                          ("Test", "test@example.com", "123", "unused", "2026-09-22"))
            site.get_db().commit()
        with self.client.session_transaction() as session:
            session["user_id"] = 1
        self.email = patch.object(site, "send_order_emails")
        self.email.start()
        self.stripe = patch.object(site.stripe.checkout.Session, "create")
        self.charge = self.stripe.start()

    def tearDown(self):
        self.charge.assert_not_called()
        self.stripe.stop()
        self.email.stop()
        self.config.stop()
        self.temp.cleanup()

    def payload(self, **extra):
        return dict(items={"0": 1}, container=0, age=True, airtight=True, safety=True, **extra)

    def test_pickup_total_and_persisted_tax(self):
        response = self.client.post("/api/order", json=self.payload(payment="pickup", total=1, tax_amount=0))
        self.assertEqual(response.status_code, 200)
        order = response.json["order"]
        self.assertEqual((order["subtotal"], order["tax_amount"], order["total"]), (35, 2.10, 37.10))
        self.assertEqual(order["payment"], "pickup")
        self.assertEqual(order["payment_status"], "unpaid")
        self.assertIsNone(response.json["checkout_url"])
        with site.app.app_context():
            saved = site.query_db("SELECT * FROM orders WHERE id=%s", (order["id"],), fetchone=True)
            self.assertEqual(saved["tax_amount"], 2.10)
        html = self.client.get("/order/" + order["id"] + "/confirm").get_data(as_text=True)
        self.assertIn("Kentucky sales tax (6%)", html)
        self.assertIn("37.10", html)

    def test_container_is_in_taxable_subtotal_and_default_is_pickup(self):
        payload = self.payload()
        payload["container"] = 10
        order = self.client.post("/api/order", json=payload).json["order"]
        self.assertEqual((order["subtotal"], order["tax_amount"], order["total"]), (45, 2.70, 47.70))

    def test_online_payment_is_rejected_before_order_creation(self):
        self.assertEqual(self.client.post("/api/order", json=self.payload(payment="online")).status_code, 400)
        with site.app.app_context():
            self.assertEqual(site.query_db("SELECT COUNT(*) AS n FROM orders", fetchone=True)["n"], 0)

    def test_checkout_shows_only_pickup_and_tax(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn('value="online"', html)
        self.assertIn('value="pickup" checked', html)
        self.assertIn('id="taxTotal"', html)
        self.assertNotIn('id="billingLine1"', html)

    def test_email_templates_show_tax(self):
        order = self.client.post("/api/order", json=self.payload()).json["order"]
        with site.app.test_request_context():
            for name in ("order_customer.html", "order_admin.html"):
                html = site.render_template("email/" + name, order=order, biz=site.BUSINESS,
                    customer_name="Test", customer_email="test@example.com", customer_phone="123",
                    order_history_url="/orders", admin_orders_url="/admin/orders")
                self.assertIn("Kentucky sales tax (6%)", html)
                self.assertIn("2.10", html)

if __name__ == "__main__":
    unittest.main()
