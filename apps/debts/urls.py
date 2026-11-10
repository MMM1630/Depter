from django.urls import path

from . import views

urlpatterns = [
    path("", views.Dashboard.as_view(), name="dashboard"),
    path("debt/new/", views.AddDebt.as_view(), name="debt_add"),
    path("customers/", views.CustomerList.as_view(), name="customer_list"),
    path("customers/<int:pk>/", views.CustomerDetail.as_view(), name="customer_detail"),
    path("customers/<int:pk>/debt/", views.CustomerAddDebt.as_view(), name="customer_debt"),
    path("customers/<int:pk>/repay/", views.CustomerRepay.as_view(), name="customer_repay"),
]
