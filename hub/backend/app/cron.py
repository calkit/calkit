"""Jobs that run on a schedule, which ``rq cron`` queues for the worker.

The schedule lives in the ``cron`` service's process, rather than as jobs
waiting in Valkey, which can evict or lose them.
"""

from rq.cron import register

from app.users import refresh_idle_box_tokens

# Box connections lapse after 60 days unused
register(
    refresh_idle_box_tokens,
    "warm",
    cron="17 9 * * *",
    job_timeout=3600,
    name="box-keepalive",
)
