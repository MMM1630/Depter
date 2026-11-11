import threading
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, connections, transaction
from django.http import Http404
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import AuditLog, ImmutableRecordError, Organization, User
from apps.shops.models import Branch

from . import services
from .models import Customer, Transaction
from .services import DomainError, balance_of


def make_org(name="Org"):
    org = Organization.objects.create(name=name)
    owner = User.objects.create_user(f"{name}-owner", password="pass-12345-x", role="owner",
                                     organization=org, first_name="Owner")
    branch = Branch.objects.create(organization=org, name=f"{name} main")
    seller = User.objects.create_user(f"{name}-seller", password="pass-12345-x", role="seller",
                                      organization=org, branch=branch)
    return org, owner, seller, branch


def debt(user, branch, name="Нурсултан", amount="500", **kw):
    return services.add_debt_by_name(
        user=user, branch_id=branch.pk, name=name, amount=amount,
        on_date=kw.pop("on_date", timezone.localdate()), key=kw.pop("key", uuid.uuid4()), **kw)


class FinanceBase(TestCase):
    def setUp(self):
        self.org, self.owner, self.seller, self.branch = make_org("A")


class DebtAndRepayTests(FinanceBase):
    def test_debt_creates_customer_and_balance(self):
        out = debt(self.seller, self.branch, amount="500")
        self.assertEqual(balance_of(out.customer.pk), Decimal("500"))

    def test_full_repay_closes_all_debts(self):
        c = debt(self.seller, self.branch, amount="500").customer
        services.add_debt(user=self.seller, customer_id=c.pk, amount=Decimal("200"),
                          on_date=timezone.localdate(), key=uuid.uuid4())
        services.repay(user=self.seller, customer_id=c.pk, mode="full", key=uuid.uuid4())
        self.assertEqual(balance_of(c.pk), 0)

    def test_partial_repay_subtracts(self):
        c = debt(self.seller, self.branch, amount="500").customer
        services.repay(user=self.seller, customer_id=c.pk, mode="partial",
                       amount=Decimal("120.50"), key=uuid.uuid4())
        self.assertEqual(balance_of(c.pk), Decimal("379.50"))

    def test_cannot_overpay_or_pay_without_debt(self):
        c = debt(self.seller, self.branch, amount="100").customer
        with self.assertRaises(DomainError):
            services.repay(user=self.seller, customer_id=c.pk, mode="partial",
                           amount=Decimal("100.01"), key=uuid.uuid4())
        services.repay(user=self.seller, customer_id=c.pk, mode="full", key=uuid.uuid4())
        with self.assertRaises(DomainError):
            services.repay(user=self.seller, customer_id=c.pk, mode="full", key=uuid.uuid4())
        self.assertEqual(balance_of(c.pk), 0)

    def test_rejects_non_positive_amounts(self):
        for bad in ("0", "-5", "abc"):
            with self.assertRaises(DomainError):
                debt(self.seller, self.branch, amount=bad)

    def test_future_date_rejected(self):
        with self.assertRaises(DomainError):
            debt(self.seller, self.branch, on_date=timezone.localdate() + timedelta(days=1))

    def test_backdated_debt_keeps_registration_time(self):
        past = timezone.localdate() - timedelta(days=10)
        t = debt(self.seller, self.branch, on_date=past).txn
        self.assertEqual(timezone.localtime(t.occurred_at).date(), past)
        self.assertEqual(timezone.localdate(t.created_at), timezone.localdate())

    def test_customer_names_normalized_no_duplicates(self):
        a = debt(self.seller, self.branch, name="Нурсултан").customer
        b = debt(self.seller, self.branch, name="  нурСУЛТАН ").customer
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Customer.objects.count(), 1)

    def test_db_unique_constraint_on_normalized_name(self):
        Customer.objects.create(branch=self.branch, name="Аман")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Customer.objects.create(branch=self.branch, name=" аМАН ")


class IdempotencyTests(FinanceBase):
    def test_same_key_does_not_duplicate_debt(self):
        key = uuid.uuid4()
        first = debt(self.seller, self.branch, key=key)
        second = debt(self.seller, self.branch, key=key)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.txn.pk, second.txn.pk)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_same_key_does_not_duplicate_repay(self):
        c = debt(self.seller, self.branch, amount="500").customer
        key = uuid.uuid4()
        services.repay(user=self.seller, customer_id=c.pk, mode="partial", amount=Decimal("100"), key=key)
        again = services.repay(user=self.seller, customer_id=c.pk, mode="partial", amount=Decimal("100"), key=key)
        self.assertTrue(again.duplicate)
        self.assertEqual(balance_of(c.pk), Decimal("400"))

    def test_http_double_post_creates_one_record(self):
        c = debt(self.seller, self.branch, amount="500").customer
        self.client.force_login(self.seller)
        page = self.client.get(reverse("customer_repay", args=[c.pk]))
        token = page.context["form"].initial["token"]
        data = {"mode": "partial", "amount": "100", "token": str(token)}
        self.client.post(reverse("customer_repay", args=[c.pk]), data)
        self.client.post(reverse("customer_repay", args=[c.pk]), data)
        self.assertEqual(Transaction.objects.filter(kind="payment").count(), 1)
        self.assertEqual(balance_of(c.pk), Decimal("400"))

    def test_missing_token_is_rejected(self):
        c = debt(self.seller, self.branch).customer
        self.client.force_login(self.seller)
        r = self.client.post(reverse("customer_repay", args=[c.pk]), {"mode": "full"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Transaction.objects.filter(kind="payment").count(), 0)

    def test_foreign_user_cannot_reuse_someone_elses_key(self):
        key = uuid.uuid4()
        debt(self.seller, self.branch, key=key)
        other = User.objects.create_user("s2", password="pass-12345-x", role="seller",
                                         organization=self.org, branch=self.branch)
        with self.assertRaises(DomainError):
            debt(other, self.branch, key=key)


class ImmutabilityTests(FinanceBase):
    def setUp(self):
        super().setUp()
        self.txn = debt(self.seller, self.branch).txn

    def test_cannot_update_or_delete_instance(self):
        self.txn.amount = Decimal("1")
        with self.assertRaises(ImmutableRecordError):
            self.txn.save()
        with self.assertRaises(ImmutableRecordError):
            self.txn.delete()

    def test_cannot_bulk_update_or_delete(self):
        with self.assertRaises(ImmutableRecordError):
            Transaction.objects.all().update(amount=1)
        with self.assertRaises(ImmutableRecordError):
            Transaction.objects.all().delete()

    def test_db_rejects_non_positive_amount(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Transaction.objects.create(customer=self.txn.customer, kind="debt", amount=Decimal("0"),
                                       created_by=self.seller)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Transaction.objects.create(customer=self.txn.customer, kind="debt", amount=Decimal("-1"),
                                       created_by=self.seller)

    def test_db_rejects_invalid_kind(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Transaction.objects.create(customer=self.txn.customer, kind="gift", amount=Decimal("1"),
                                       created_by=self.seller)

    def test_branch_and_customer_with_history_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.txn.customer.delete()
        with self.assertRaises(ProtectedError):
            self.branch.delete()

    def test_user_with_transactions_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.seller.delete()

    def test_audit_log_is_append_only(self):
        entry = AuditLog.objects.first()
        entry.action = "x"
        with self.assertRaises(ImmutableRecordError):
            entry.save()
        with self.assertRaises(ImmutableRecordError):
            entry.delete()


class ReversalTests(FinanceBase):
    def test_reverse_debt_creates_compensating_record(self):
        out = debt(self.seller, self.branch, amount="500")
        services.reverse_transaction(user=self.owner, txn_id=out.txn.pk, reason="ошибка", key=uuid.uuid4())
        self.assertEqual(Transaction.objects.count(), 2)  # исходная осталась
        self.assertEqual(balance_of(out.customer.pk), 0)
        self.assertTrue(Transaction.objects.filter(reversal_of=out.txn).exists())

    def test_reverse_payment_restores_debt(self):
        c = debt(self.seller, self.branch, amount="500").customer
        pay = services.repay(user=self.seller, customer_id=c.pk, mode="full", key=uuid.uuid4())
        services.reverse_transaction(user=self.owner, txn_id=pay.txn.pk, reason="ошибка", key=uuid.uuid4())
        self.assertEqual(balance_of(c.pk), Decimal("500"))

    def test_cannot_reverse_twice_or_reverse_a_reversal(self):
        out = debt(self.seller, self.branch)
        rev = services.reverse_transaction(user=self.owner, txn_id=out.txn.pk, reason="r", key=uuid.uuid4())
        with self.assertRaises(DomainError):
            services.reverse_transaction(user=self.owner, txn_id=out.txn.pk, reason="r", key=uuid.uuid4())
        with self.assertRaises(DomainError):
            services.reverse_transaction(user=self.owner, txn_id=rev.txn.pk, reason="r", key=uuid.uuid4())

    def test_reversal_cannot_make_balance_negative(self):
        c = debt(self.seller, self.branch, amount="500").customer
        services.repay(user=self.seller, customer_id=c.pk, mode="partial", amount=Decimal("300"), key=uuid.uuid4())
        first_debt = Transaction.objects.get(kind="debt")
        with self.assertRaises(DomainError):
            services.reverse_transaction(user=self.owner, txn_id=first_debt.pk, reason="r", key=uuid.uuid4())
        self.assertEqual(balance_of(c.pk), Decimal("200"))

    def test_seller_cannot_reverse(self):
        out = debt(self.seller, self.branch)
        with self.assertRaises(PermissionDenied):
            services.reverse_transaction(user=self.seller, txn_id=out.txn.pk, reason="r", key=uuid.uuid4())

    def test_reversal_is_excluded_from_effective_totals(self):
        out = debt(self.seller, self.branch, amount="500")
        debt(self.seller, self.branch, name="Другой", amount="100")
        services.reverse_transaction(user=self.owner, txn_id=out.txn.pk, reason="r", key=uuid.uuid4())
        self.assertEqual(Transaction.objects.effective().count(), 1)
        self.client.force_login(self.owner)
        ctx = self.client.get(reverse("dashboard")).context
        self.assertEqual(ctx["given"], 100)
        self.assertEqual(ctx["owed"], 100)


class BlockArchiveTests(FinanceBase):
    def test_blocked_customer_cannot_get_new_debt(self):
        c = debt(self.seller, self.branch).customer
        services.set_customer_flag(user=self.owner, customer_id=c.pk, flag="is_blocked", value=True)
        with self.assertRaises(DomainError):
            services.add_debt(user=self.seller, customer_id=c.pk, amount=Decimal("1"),
                              on_date=timezone.localdate(), key=uuid.uuid4())
        with self.assertRaises(DomainError):
            debt(self.seller, self.branch)  # тот же клиент по имени

    def test_blocked_customer_can_still_repay(self):
        c = debt(self.seller, self.branch).customer
        services.set_customer_flag(user=self.owner, customer_id=c.pk, flag="is_blocked", value=True)
        services.repay(user=self.seller, customer_id=c.pk, mode="full", key=uuid.uuid4())
        self.assertEqual(balance_of(c.pk), 0)

    def test_archive_requires_zero_balance_and_owner(self):
        c = debt(self.seller, self.branch).customer
        with self.assertRaises(DomainError):
            services.set_customer_flag(user=self.owner, customer_id=c.pk, flag="is_archived", value=True)
        services.repay(user=self.seller, customer_id=c.pk, mode="full", key=uuid.uuid4())
        with self.assertRaises(PermissionDenied):
            services.set_customer_flag(user=self.seller, customer_id=c.pk, flag="is_archived", value=True)
        services.set_customer_flag(user=self.owner, customer_id=c.pk, flag="is_archived", value=True)
        self.assertTrue(Customer.objects.get(pk=c.pk).is_archived)

    def test_archived_branch_rejects_new_debts(self):
        c = debt(self.seller, self.branch).customer
        self.branch.is_active = False
        self.branch.save()
        with self.assertRaises(DomainError):
            services.add_debt(user=self.owner, customer_id=c.pk, amount=Decimal("1"),
                              on_date=timezone.localdate(), key=uuid.uuid4())


class AuditTests(FinanceBase):
    def test_financial_actions_are_logged(self):
        c = debt(self.seller, self.branch).customer
        services.repay(user=self.seller, customer_id=c.pk, mode="full", key=uuid.uuid4())
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"debt.add", "payment.add"} <= actions)
        log = AuditLog.objects.get(action="payment.add")
        self.assertEqual(log.username, self.seller.username)
        self.assertEqual(log.organization_id, self.org.pk)

    def test_audit_http_login_records_ip(self):
        self.client.post(reverse("login"), {"username": self.owner.username, "password": "pass-12345-x"},
                         REMOTE_ADDR="10.1.2.3")
        entry = AuditLog.objects.get(action="auth.login")
        self.assertEqual(entry.ip, "10.1.2.3")

    def test_failed_operation_leaves_no_audit_or_transaction(self):
        c = debt(self.seller, self.branch, amount="10").customer
        before = (Transaction.objects.count(), AuditLog.objects.count())
        with self.assertRaises(DomainError):
            services.repay(user=self.seller, customer_id=c.pk, mode="partial",
                           amount=Decimal("99"), key=uuid.uuid4())
        self.assertEqual((Transaction.objects.count(), AuditLog.objects.count()), before)


class ExportTests(FinanceBase):
    def test_csv_export_owner_only_and_escapes_formulas(self):
        debt(self.seller, self.branch, name="=HYPERLINK(1)", amount="500")
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(reverse("export_csv")).status_code, 403)
        self.client.force_login(self.owner)
        r = self.client.get(reverse("export_csv"))
        self.assertEqual(r.status_code, 200)
        body = b"".join(r.streaming_content).decode("utf-8-sig")
        self.assertIn("'=HYPERLINK(1)", body)
        self.assertNotIn(",=HYPERLINK", body)
        self.assertTrue(AuditLog.objects.filter(action="export.csv").exists())

    def test_export_excludes_other_organizations(self):
        _, o2, s2, b2 = make_org("B")
        debt(s2, b2, name="Чужой")
        debt(self.seller, self.branch, name="Свой")
        self.client.force_login(self.owner)
        body = b"".join(self.client.get(reverse("export_csv")).streaming_content).decode("utf-8-sig")
        self.assertIn("Свой", body)
        self.assertNotIn("Чужой", body)


class PaginationTests(FinanceBase):
    def test_customer_list_is_paginated(self):
        Customer.objects.bulk_create([Customer(branch=self.branch, name=f"Клиент {i:03}", name_key=f"клиент {i:03}")
                                      for i in range(60)])
        self.client.force_login(self.owner)
        r = self.client.get(reverse("customer_list") + "?all=1")
        self.assertEqual(len(r.context["object_list"]), 25)
        self.assertTrue(r.context["page_obj"].has_next())

    def test_history_is_paginated(self):
        c = debt(self.seller, self.branch, amount="1").customer
        for _ in range(40):
            services.add_debt(user=self.seller, customer_id=c.pk, amount=Decimal("1"),
                              on_date=timezone.localdate(), key=uuid.uuid4())
        self.client.force_login(self.owner)
        r = self.client.get(reverse("customer_detail", args=[c.pk]))
        self.assertEqual(len(r.context["page_obj"].object_list), 30)
        self.assertEqual(r.context["page_obj"].paginator.count, 41)


class ConcurrencyTests(TransactionTestCase):
    """Настоящая гонка потоков. Имеет смысл только на PostgreSQL (SQLite не блокирует строки)."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("нужен PostgreSQL (DB_NAME в .env)")
        self.org, self.owner, self.seller, self.branch = make_org("C")
        self.customer = debt(self.seller, self.branch, amount="100").customer

    def _race(self, fn, n=8):
        barrier, results = threading.Barrier(n), []

        def worker():
            try:
                barrier.wait()
                results.append(("ok", fn()))
            except DomainError as e:
                results.append(("domain", e.key))
            except Exception as e:  # noqa
                results.append(("error", repr(e)))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(n)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        return results

    def test_parallel_repayments_never_overpay(self):
        res = self._race(lambda: services.repay(user=self.seller, customer_id=self.customer.pk,
                                                mode="partial", amount=Decimal("60"), key=uuid.uuid4()))
        self.assertEqual([r for r in res if r[0] == "error"], [])
        self.assertEqual(sum(1 for r in res if r[0] == "ok"), 1)  # 60 + 60 > 100
        self.assertEqual(balance_of(self.customer.pk), Decimal("40"))

    def test_parallel_full_repay_creates_one_payment(self):
        res = self._race(lambda: services.repay(user=self.seller, customer_id=self.customer.pk,
                                                mode="full", key=uuid.uuid4()))
        self.assertEqual([r for r in res if r[0] == "error"], [])
        self.assertEqual(Transaction.objects.filter(kind="payment").count(), 1)
        self.assertEqual(balance_of(self.customer.pk), 0)

    def test_parallel_same_key_creates_one_payment(self):
        key = uuid.uuid4()
        res = self._race(lambda: services.repay(user=self.seller, customer_id=self.customer.pk,
                                                mode="partial", amount=Decimal("10"), key=key))
        self.assertEqual([r for r in res if r[0] == "error"], [])
        self.assertEqual(Transaction.objects.filter(kind="payment").count(), 1)
        self.assertEqual(balance_of(self.customer.pk), Decimal("90"))

    def test_parallel_new_customer_same_name_no_duplicates(self):
        res = self._race(lambda: debt(self.seller, self.branch, name="Новый клиент", amount="5"))
        self.assertEqual([r for r in res if r[0] == "error"], [])
        self.assertEqual(Customer.objects.filter(name_key="новый клиент").count(), 1)
        self.assertEqual(Transaction.objects.filter(customer__name="Новый клиент").count(), 8)
        self.assertEqual(balance_of(Customer.objects.get(name_key="новый клиент").pk), Decimal("40"))

    def test_parallel_reversals_create_one_compensation(self):
        res = self._race(lambda: services.reverse_transaction(
            user=self.owner, txn_id=Transaction.objects.get(kind="debt").pk, reason="r", key=uuid.uuid4()))
        self.assertEqual([r for r in res if r[0] == "error"], [])
        self.assertEqual(Transaction.objects.filter(reversal_of__isnull=False).count(), 1)
        self.assertEqual(balance_of(self.customer.pk), 0)
