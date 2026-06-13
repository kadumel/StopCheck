from django.db.models.signals import post_save
from django.dispatch import receiver

from stop_check.models import DailyComparison
from stop_check.services.revenue_service import sync_revenue_for_comparison


@receiver(post_save, sender=DailyComparison)
def sync_revenue_on_comparison_save(sender, instance, **kwargs):
    sync_revenue_for_comparison(instance)
