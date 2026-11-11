from django.urls import path

from . import views

urlpatterns = [
    path("", views.Dashboard.as_view(), name="dashboard"),
    path("debt/new/", views.AddDebt.as_view(), name="debt_add"),
    path("customers/", views.CustomerList.as_view(), name="customer_list"),
    path("customers/<int:pk>/", views.CustomerDetail.as_view(), name="customer_detail"),
    path("customers/<int:pk>/debt/", views.CustomerAddDebt.as_view(), name="customer_debt"),
    path("customers/<int:pk>/repay/", views.CustomerRepay.as_view(), name="customer_repay"),
    path("customers/<int:pk>/block/", views.CustomerFlag.as_view(
        flag="is_blocked", value=True, message_key="msg_blocked"), name="customer_block"),
    path("customers/<int:pk>/unblock/", views.CustomerFlag.as_view(
        flag="is_blocked", value=False, message_key="msg_unblocked"), name="customer_unblock"),
    path("customers/<int:pk>/archive/", views.CustomerFlag.as_view(
        flag="is_archived", value=True, message_key="msg_archived"), name="customer_archive"),
    path("customers/<int:pk>/restore/", views.CustomerFlag.as_view(
        flag="is_archived", value=False, message_key="msg_restored"), name="customer_restore"),
    path("transactions/<int:pk>/reverse/", views.TransactionReverse.as_view(), name="txn_reverse"),
    path("export/transactions.csv", views.ExportCSV.as_view(), name="export_csv"),
]
