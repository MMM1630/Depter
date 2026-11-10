from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.Login.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.Register.as_view(), name="register"),
    path("lang/<str:code>/", views.set_language, name="set_lang"),
    path("workers/", views.WorkerList.as_view(), name="worker_list"),
    path("workers/new/", views.WorkerCreate.as_view(), name="worker_create"),
    path("workers/<int:pk>/edit/", views.WorkerUpdate.as_view(), name="worker_update"),
    path("workers/<int:pk>/delete/", views.WorkerDelete.as_view(), name="worker_delete"),
]
