import allianceauth.urls
from django.urls import include, path

urlpatterns = [
    path("recruitment/", include("aa_recruitment.urls", namespace="aa_recruitment")),
    path("", include("aa_recruitment.urls", namespace="aa_recruitment")),
    path("", include(allianceauth.urls)),
]
