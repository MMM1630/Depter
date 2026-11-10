from django.urls import path
from . import views

urlpatterns = [
    path("branches/", views.BranchList.as_view(), name="branch_list"),
    path("branches/new/", views.BranchCreate.as_view(), name="branch_create"),
    path("branches/<int:pk>/edit/", views.BranchUpdate.as_view(), name="branch_update"),
    path("branches/<int:pk>/delete/", views.BranchDelete.as_view(), name="branch_delete"),
]
