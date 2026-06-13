from django.apps import AppConfig


class StopCheckConfig(AppConfig):
    name = 'stop_check'

    def ready(self):
        import stop_check.signals  # noqa: F401
