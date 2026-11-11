import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.debts import services
from apps.debts.models import Customer, Transaction
from apps.debts.tests import debt, make_org
from apps.shops.models import Branch

from .models import AuditLog, Organization, User


class IsolationBase(TestCase):
    def setUp(self):
        cache.clear()
        self.org_a, self.owner_a, self.seller_a, self.branch_a = make_org("A")
        self.org_b, self.owner_b, self.seller_b, self.branch_b = make_org("B")
        self.second_a = Branch.objects.create(organization=self.org_a, name="A second")
        self.cust_a = debt(self.seller_a, self.branch_a, name="Клиент А").customer
        self.cust_b = debt(self.seller_b, self.branch_b, name="Клиент Б").customer
        self.cust_a2 = debt(self.owner_a, self.second_a, name="Клиент А2").customer
        self.txn_b = Transaction.objects.get(customer=self.cust_b)


class IDORTests(IsolationBase):
    """Горизонтальное повышение привилегий: чужие объекты по прямым ссылкам."""

    def test_other_org_customer_pages_are_404(self):
        self.client.force_login(self.owner_a)
        for name in ("customer_detail", "customer_debt", "customer_repay"):
            self.assertEqual(self.client.get(reverse(name, args=[self.cust_b.pk])).status_code, 404, name)

    def test_other_org_post_actions_are_404_and_change_nothing(self):
        self.client.force_login(self.owner_a)
        before = Transaction.objects.count()
        r = self.client.post(reverse("customer_repay", args=[self.cust_b.pk]),
                             {"mode": "full", "token": str(uuid.uuid4())})
        self.assertEqual(r.status_code, 404)
        r = self.client.post(reverse("customer_debt", args=[self.cust_b.pk]),
                             {"amount": "5", "date": timezone.localdate().isoformat(), "token": str(uuid.uuid4())})
        self.assertEqual(r.status_code, 404)
        for name in ("customer_block", "customer_archive"):
            self.assertEqual(self.client.post(reverse(name, args=[self.cust_b.pk])).status_code, 404, name)
        self.assertEqual(Transaction.objects.count(), before)
        self.assertFalse(Customer.objects.get(pk=self.cust_b.pk).is_blocked)

    def test_cannot_reverse_other_org_transaction(self):
        self.client.force_login(self.owner_a)
        r = self.client.post(reverse("txn_reverse", args=[self.txn_b.pk]),
                             {"reason": "x", "token": str(uuid.uuid4())})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Transaction.objects.filter(reversal_of=self.txn_b).count(), 0)

    def test_cannot_add_debt_to_other_org_branch(self):
        self.client.force_login(self.owner_a)
        r = self.client.post(reverse("debt_add"), {
            "branch": self.branch_b.pk, "customer_name": "Взлом", "amount": "10",
            "date": timezone.localdate().isoformat(), "token": str(uuid.uuid4())})
        self.assertEqual(r.status_code, 200)  # форма невалидна: филиала нет в списке
        self.assertFalse(Customer.objects.filter(name="Взлом").exists())

    def test_other_org_branch_and_worker_pages_are_404(self):
        self.client.force_login(self.owner_a)
        self.assertEqual(self.client.get(reverse("branch_update", args=[self.branch_b.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("branch_toggle", args=[self.branch_b.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("worker_update", args=[self.seller_b.pk])).status_code, 404)

    def test_lists_never_leak_other_org_data(self):
        self.client.force_login(self.owner_a)
        page = self.client.get(reverse("customer_list") + "?all=1").content.decode()
        self.assertIn("Клиент А", page)
        self.assertNotIn("Клиент Б", page)
        dash = self.client.get(reverse("dashboard")).context
        self.assertEqual(dash["given"], 1000)  # только 500 + 500 организации A

    def test_worker_cannot_be_assigned_to_foreign_branch(self):
        self.client.force_login(self.owner_a)
        r = self.client.post(reverse("worker_create"), {
            "username": "newguy", "first_name": "N", "branch": self.branch_b.pk,
            "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="newguy").exists())

    def test_seller_sees_only_own_branch(self):
        self.client.force_login(self.seller_a)
        page = self.client.get(reverse("customer_list") + "?all=1").content.decode()
        self.assertIn("Клиент А", page)
        self.assertNotIn("Клиент А2", page)  # другой филиал той же организации
        self.assertEqual(self.client.get(reverse("customer_detail", args=[self.cust_a2.pk])).status_code, 404)


class RoleTests(IsolationBase):
    OWNER_ONLY = ["branch_list", "branch_create", "worker_list", "worker_create", "audit_list", "export_csv"]

    def test_seller_forbidden_on_owner_pages(self):
        self.client.force_login(self.seller_a)
        for name in self.OWNER_ONLY:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        for name, args in (("branch_update", [self.branch_a.pk]), ("worker_update", [self.seller_a.pk]),
                           ("txn_reverse", [Transaction.objects.first().pk])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403, name)
        for name in ("customer_block", "customer_unblock", "customer_archive", "customer_restore"):
            self.assertEqual(self.client.post(reverse(name, args=[self.cust_a.pk])).status_code, 403, name)
        self.assertEqual(self.client.post(reverse("branch_toggle", args=[self.branch_a.pk])).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        for name in ("dashboard", "customer_list", "debt_add", "branch_list", "worker_list", "audit_list"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn(reverse("login"), r["Location"])

    def test_seller_can_add_debt_and_repay(self):
        self.client.force_login(self.seller_a)
        r = self.client.post(reverse("customer_repay", args=[self.cust_a.pk]),
                             {"mode": "full", "token": str(uuid.uuid4())})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(services.balance_of(self.cust_a.pk), 0)

    def test_seller_cannot_forge_owner_role_via_worker_edit(self):
        self.client.force_login(self.seller_a)
        r = self.client.post(reverse("worker_update", args=[self.seller_a.pk]),
                             {"first_name": "x", "branch": self.branch_a.pk, "role": "owner"})
        self.assertEqual(r.status_code, 403)
        self.seller_a.refresh_from_db()
        self.assertEqual(self.seller_a.role, "seller")

    def test_owner_edit_form_cannot_change_role(self):
        self.client.force_login(self.owner_a)
        self.client.post(reverse("worker_update", args=[self.seller_a.pk]), {
            "first_name": "Renamed", "branch": self.branch_a.pk, "is_active": "on",
            "role": "owner", "organization": self.org_b.pk})
        self.seller_a.refresh_from_db()
        self.assertEqual(self.seller_a.role, "seller")
        self.assertEqual(self.seller_a.organization_id, self.org_a.pk)

    def test_inactive_worker_cannot_log_in(self):
        self.seller_a.is_active = False
        self.seller_a.save()
        r = self.client.post(reverse("login"), {"username": self.seller_a.username, "password": "pass-12345-x"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_superuser_without_org_sees_nothing_in_app(self):
        su = User.objects.create_superuser("root", password="pass-12345-x")
        self.client.force_login(su)
        r = self.client.get(reverse("customer_list") + "?all=1")
        self.assertEqual(len(r.context["object_list"]), 0)
        self.assertEqual(self.client.get(reverse("branch_list")).status_code, 403)


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_register_creates_org_owner_and_branch(self):
        r = self.client.post(reverse("register"), {
            "organization_name": "Магазин Алтын", "first_name": "Айбек", "username": "aibek",
            "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99"})
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username="aibek")
        self.assertEqual(u.role, "owner")
        self.assertEqual(u.organization.name, "Магазин Алтын")
        self.assertEqual(Branch.objects.filter(organization=u.organization).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="org.register").exists())

    def test_two_registrations_do_not_share_data(self):
        for n in ("one", "two"):
            self.client.logout()
            self.client.post(reverse("register"), {
                "organization_name": n, "first_name": n, "username": n,
                "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99"}, REMOTE_ADDR=f"10.0.0.{len(n)}{ord(n[0])%9}")
        self.assertEqual(Organization.objects.count(), 2)
        self.assertNotEqual(User.objects.get(username="one").organization_id,
                            User.objects.get(username="two").organization_id)

    def test_cannot_register_as_seller_or_into_foreign_org(self):
        org = Organization.objects.create(name="Victim")
        self.client.post(reverse("register"), {
            "organization_name": "x", "first_name": "x", "username": "evil", "role": "seller",
            "organization": org.pk, "is_superuser": "on", "is_staff": "on",
            "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99"})
        u = User.objects.get(username="evil")
        self.assertEqual(u.role, "owner")
        self.assertNotEqual(u.organization_id, org.pk)
        self.assertFalse(u.is_superuser or u.is_staff)

    def test_weak_password_rejected(self):
        r = self.client.post(reverse("register"), {
            "organization_name": "x", "first_name": "x", "username": "weak",
            "password1": "12345678", "password2": "12345678"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="weak").exists())

    def test_registration_is_rate_limited(self):
        statuses = []
        for i in range(7):
            r = self.client.post(reverse("register"), {
                "organization_name": f"o{i}", "first_name": "x", "username": f"user{i}",
                "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99"}, REMOTE_ADDR="10.9.9.9")
            statuses.append(r.status_code)
            self.client.logout()
        self.assertEqual(statuses[:5], [302] * 5)
        self.assertEqual(statuses[5:], [200, 200])
        self.assertFalse(User.objects.filter(username="user6").exists())


class AdminSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org, self.owner, self.seller, self.branch = make_org("A")
        self.su = User.objects.create_superuser("root", password="pass-12345-x")
        self.out = debt(self.seller, self.branch)

    def admin(self, path=""):
        from django.conf import settings
        return "/" + settings.ADMIN_URL + path

    def test_owner_and_seller_cannot_enter_admin(self):
        for u in (self.owner, self.seller):
            self.client.force_login(u)
            r = self.client.get(self.admin())
            self.assertEqual(r.status_code, 302, u)
            self.assertIn("login", r["Location"])

    def test_default_admin_url_is_gone(self):
        self.client.force_login(self.su)
        self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_transaction_is_read_only_in_admin(self):
        self.client.force_login(self.su)
        t = self.out.txn
        self.assertEqual(self.client.get(self.admin("debts/transaction/")).status_code, 200)
        self.assertEqual(self.client.get(self.admin("debts/transaction/add/")).status_code, 403)
        r = self.client.post(self.admin(f"debts/transaction/{t.pk}/change/"), {"amount": "1"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post(self.admin(f"debts/transaction/{t.pk}/delete/"), {"post": "yes"})
        self.assertEqual(r.status_code, 403)
        t.refresh_from_db()
        self.assertEqual(t.amount, Decimal("500.00"))

    def test_admin_actions_cannot_delete_financial_or_audit_rows(self):
        self.client.force_login(self.su)
        for model, pk in (("debts/transaction", self.out.txn.pk), ("accounts/auditlog", AuditLog.objects.first().pk),
                          ("debts/customer", self.out.customer.pk), ("shops/branch", self.branch.pk)):
            r = self.client.post(self.admin(f"{model}/{pk}/delete/"), {"post": "yes"})
            self.assertEqual(r.status_code, 403, model)
        self.assertTrue(Transaction.objects.exists())
        self.assertTrue(Customer.objects.exists())
        self.assertTrue(Branch.objects.exists())

    def test_bulk_delete_action_is_unavailable(self):
        self.client.force_login(self.su)
        r = self.client.post(self.admin("debts/transaction/"), {
            "action": "delete_selected", "_selected_action": [self.out.txn.pk]})
        self.assertIn(r.status_code, (200, 302))
        self.assertTrue(Transaction.objects.exists())


class LoginProtectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org, self.owner, self.seller, self.branch = make_org("A")

    def attempt(self, user, password, ip="10.0.0.1"):
        return self.client.post(reverse("login"), {"username": user, "password": password}, REMOTE_ADDR=ip)

    def test_lockout_after_five_failures_even_with_right_password(self):
        for _ in range(5):
            self.attempt(self.owner.username, "wrong")
        r = self.attempt(self.owner.username, "pass-12345-x")
        self.assertEqual(r.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lockout_is_per_ip_and_username(self):
        for _ in range(5):
            self.attempt(self.owner.username, "wrong", ip="10.0.0.1")
        other_user = self.attempt(self.seller.username, "pass-12345-x", ip="10.0.0.1")
        self.assertEqual(other_user.status_code, 302)
        self.client.logout()
        other_ip = self.attempt(self.owner.username, "pass-12345-x", ip="10.0.0.2")
        self.assertEqual(other_ip.status_code, 302)

    def test_successful_login_resets_counter(self):
        for _ in range(3):
            self.attempt(self.owner.username, "wrong")
        self.assertEqual(self.attempt(self.owner.username, "pass-12345-x").status_code, 302)
        self.client.logout()
        for _ in range(3):
            self.attempt(self.owner.username, "wrong")
        self.assertEqual(self.attempt(self.owner.username, "pass-12345-x").status_code, 302)

    def test_lockout_applies_to_admin_login_too(self):
        from django.conf import settings
        su = User.objects.create_superuser("root", password="pass-12345-x")
        url = "/" + settings.ADMIN_URL + "login/"
        for _ in range(5):
            self.client.post(url, {"username": su.username, "password": "wrong", "next": "/"}, REMOTE_ADDR="10.7.7.7")
        r = self.client.post(url, {"username": su.username, "password": "pass-12345-x", "next": "/"},
                             REMOTE_ADDR="10.7.7.7")
        self.assertEqual(r.status_code, 429)


class SecuritySettingsTests(TestCase):
    def test_cookie_and_header_flags(self):
        from django.conf import settings
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertTrue(settings.DATABASES["default"]["ATOMIC_REQUESTS"])
        self.assertNotIn("insecure", settings.SECRET_KEY.lower())

    def test_audit_view_scoped_to_organization(self):
        cache.clear()
        _, owner_a, seller_a, branch_a = make_org("A")
        _, owner_b, seller_b, branch_b = make_org("B")
        debt(seller_b, branch_b, name="СекретБ")
        self.client.force_login(owner_a)
        page = self.client.get(reverse("audit_list")).content.decode()
        self.assertNotIn("СекретБ", page)
