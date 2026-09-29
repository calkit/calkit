"""Receive anonymous page views.

Page views are counted here rather than in the browser so that nothing has to
be stored on the visitor's device, which is what lets them be collected
without consent. The visitor is identified for the day by a keyed hash of the
request's IP address and user agent, which groups one visitor's views for the
day without being linkable across days; the raw values are never kept.
"""

import hashlib
import hmac
import re

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, Field, ValidationError

from app import mixpanel
from app.config import settings
from app.core import utcnow

router = APIRouter()

# A batch is what the browser accumulated between flushes, which is bounded on
# that side too; the cap here is what stops a crafted request from fanning out
# into unbounded work. Paths are route templates, so they are short.
MAX_VIEWS_PER_REQUEST = 50
MAX_PATH_LENGTH = 200

# User agents that name themselves as crawlers or command-line clients. Bots
# driving a real browser don't show up here, which is why the interaction
# signal exists.
_BOT_UA_RE = re.compile(
    r"bot|crawl|spider|slurp|curl|wget|python|httpclient|scrapy|headless|"
    r"phantom|selenium|puppeteer|playwright|lighthouse|pingdom|uptimerobot|"
    r"facebookexternalhit|monitor|preview",
    re.IGNORECASE,
)


class PageViewIn(BaseModel):
    # The matched route's template, e.g., "/join/$token", with no parameter
    # values, so nothing identifying is recorded
    path: str = Field(max_length=MAX_PATH_LENGTH)
    # Milliseconds between the view and the batch being sent
    dwell_ms: int = Field(default=0, ge=0)


class SignalsIn(BaseModel):
    # Whether the browser was driven (navigator.webdriver)
    webdriver: bool = False
    # Whether any real input, e.g., a pointer, key, or scroll, happened; a
    # bot that only loads pages reports none
    interacted: bool = False


class PageViewsIn(BaseModel):
    views: list[PageViewIn] = Field(max_length=MAX_VIEWS_PER_REQUEST)
    signals: SignalsIn = Field(default_factory=SignalsIn)


def _client_ip(request: Request) -> str:
    # Behind the proxy the socket address is the proxy's, so the forwarded
    # headers are what actually name the visitor
    for header in ("cf-connecting-ip", "x-real-ip"):
        value = request.headers.get(header)
        if value:
            return value.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _visitor_id(request: Request) -> str:
    """A per-day identifier derived from the request alone.

    The date is mixed in so the same visitor gets a new identifier each day,
    which is what keeps their views from being linkable over time, and the
    secret keeps the value from being reversed without it.
    """
    material = "|".join(
        [
            utcnow().date().isoformat(),
            _client_ip(request),
            request.headers.get("user-agent", ""),
        ]
    )
    digest = hmac.new(
        settings.SECRET_KEY.encode(), material.encode(), hashlib.sha256
    ).hexdigest()
    return digest[:32]


def _is_bot(signals: SignalsIn, user_agent: str) -> bool:
    return signals.webdriver or bool(_BOT_UA_RE.search(user_agent))


def _record(
    visitor_id: str,
    views: list[PageViewIn],
    bot: bool,
    interacted: bool,
) -> None:
    for view in views:
        mixpanel.track_anonymous_pageview(
            visitor_id=visitor_id,
            path=view.path,
            bot=bot,
            interacted=interacted,
            dwell_ms=view.dwell_ms,
        )


@router.post("/pageviews", status_code=204, include_in_schema=False)
async def post_pageviews(
    request: Request, background_tasks: BackgroundTasks
) -> Response:
    """Record a batch of anonymous page views.

    Deliberately unauthenticated: the visitor is not signed in for this
    purpose, and the request carries no identifier of its own. The browser
    sends this as a `text/plain` beacon, so the body is parsed by hand rather
    than through a JSON content type, which a cross-origin beacon could not
    set without a preflight. Sending to Mixpanel happens after the response,
    since a beacon has nobody waiting on it.
    """
    if not settings.MIXPANEL_TOKEN:
        return Response(status_code=204)
    try:
        payload = PageViewsIn.model_validate_json(await request.body())
    except ValidationError:
        raise HTTPException(422, "Invalid page view batch")
    user_agent = request.headers.get("user-agent", "")
    background_tasks.add_task(
        _record,
        _visitor_id(request),
        payload.views,
        _is_bot(payload.signals, user_agent),
        payload.signals.interacted,
    )
    return Response(status_code=204)
