"""
LinkedIn Games scraper using Playwright + BeautifulSoup.

Loads a saved browser state (cookies) so no interactive login is needed
on normal runs. Call setup_auth.py once to save the state in the OS credential
store.
"""

import re
import time
import random
import logging
import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page, BrowserContext

from auth_store import get_linkedin_state
from config import GAMES, GAME_IDS
from sheet_layout import load_layout

logger = logging.getLogger(__name__)


def sleep_with_jitter(seconds: float) -> None:
    """
    Sleep `seconds` with ±15% jitter to space out consecutive requests and
    reduce the chance of tripping LinkedIn's rate limiting. No-op for seconds<=0.
    """
    if seconds and seconds > 0:
        time.sleep(seconds * random.uniform(0.85, 1.15))


@dataclass
class GameResult:
    name: str
    score: Optional[str]   # "0:17" / "1:23" for time games, "3" for Pinpoint
    avg: Optional[str]     # same format as score
    number: Optional[str] = None  # puzzle number, e.g. "389"
    error: Optional[str] = None
    unplayed: bool = False  # True when the game hasn't been played yet today


def _build_game_urn(viewer_member_id: str, game_key: str, puzzle_number_str: str) -> str:
    game_id = GAME_IDS[game_key]
    return f"urn:li:fsd_game:({viewer_member_id},{game_id},{int(puzzle_number_str)})"


def _try_extract_viewer_member_id(html: str) -> Optional[str]:
    """Search page HTML for a gameUrn and extract the viewerMemberId segment."""
    m = _GAME_URN_MEMBER_RE.search(html)
    return m.group(1) if m else None


# viewerMemberId is the first segment of a gameUrn: urn:li:fsd_game:(<member>,...).
_GAME_URN_MEMBER_RE = re.compile(r"urn:li:fsd_game:\(([^,)]+),")
# The connections-leaderboard queryId hash rides on the request URL as
# queryId=voyagerIdentityDashGameConnectionsEntities.<hash>.
_LEADERBOARD_QID_RE = re.compile(r"voyagerIdentityDashGameConnectionsEntities\.([0-9a-f]{16,})")


class _VoyagerIdCapture:
    """
    Passive listener that harvests the viewer member id and the connections-
    leaderboard queryId from a page's Voyager traffic. Attach with attach(page)
    before navigating, then read .member_id / .query_id afterward.

    Both values are stable identifiers LinkedIn embeds in its own web app, so
    loading any played game's results page surfaces them with no dev tools —
    the queryId in the leaderboard request URL, the member id in gameUrns.
    """

    def __init__(self) -> None:
        self.member_id: Optional[str] = None
        self.query_id: Optional[str] = None

    def _scan_url(self, url: str) -> None:
        decoded = urllib.parse.unquote(url)
        if self.query_id is None:
            m = _LEADERBOARD_QID_RE.search(decoded)
            if m:
                self.query_id = m.group(1)
        if self.member_id is None:
            m = _GAME_URN_MEMBER_RE.search(decoded)
            if m:
                self.member_id = m.group(1)

    def _on_request(self, request) -> None:
        try:
            self._scan_url(request.url)
        except Exception:
            pass

    def _on_response(self, response) -> None:
        if self.member_id is not None:
            return
        try:
            if "voyager/api" not in response.url:
                return
            m = _GAME_URN_MEMBER_RE.search(response.text())
            if m:
                self.member_id = m.group(1)
        except Exception:
            pass

    def attach(self, page: Page) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def scan_html(self, html: str) -> None:
        """Fallback: pull the member id out of static page HTML."""
        if self.member_id is None:
            m = _GAME_URN_MEMBER_RE.search(html)
            if m:
                self.member_id = m.group(1)


def _extrapolate_puzzle_number(
    game_key: str,
    target_date: date,
    results_data: dict,
) -> Optional[int]:
    """
    Compute today's puzzle number for game_key using linear extrapolation from
    the most recent stored entry. Puzzle numbers are confirmed perfectly linear
    (+1 per day). Returns None if no prior entry exists for this game.
    """
    best_date: Optional[date] = None
    best_number: Optional[int] = None
    for date_str, rec in results_data.items():
        games = (rec or {}).get("games") or {}
        entry = (games.get(game_key) or {})
        num_str = entry.get("number")
        if not num_str:
            continue
        try:
            num = int(num_str)
            d = date.fromisoformat(date_str)
            if best_date is None or d > best_date:
                best_date = d
                best_number = num
        except (ValueError, TypeError):
            continue
    if best_date is None or best_number is None:
        return None
    return best_number + (target_date - best_date).days


def _voyager_csrf_token(context: BrowserContext) -> Optional[str]:
    """
    Return the CSRF token Voyager requires: the JSESSIONID cookie value with
    its surrounding quotes stripped. Voyager GraphQL rejects requests without a
    matching `csrf-token` header with 403 "CSRF check failed".
    """
    jsession = next((c["value"] for c in context.cookies() if c["name"] == "JSESSIONID"), None)
    return jsession.strip('"') if jsession else None


def _check_played_leaderboard(
    context: BrowserContext,
    game_key: str,
    puzzle_number: int,
    viewer_member_id: str,
    query_id: str,
    csrf_token: Optional[str],
) -> Optional[bool]:
    """
    Call the connections-leaderboard Voyager API and return True (played),
    False (unplayed), or None (API error / queryId stale). Timer-safe: does
    not load any game board page.

    The played signal is the viewer's own rank in the leaderboard snapshot
    (metadata.memberRanking), which is null until the viewer plays. The
    connections list (elements) is populated regardless, so it is NOT a
    played signal.
    """
    game_urn = _build_game_urn(viewer_member_id, game_key, str(puzzle_number))
    encoded_urn = urllib.parse.quote(game_urn, safe="")
    url = (
        "https://www.linkedin.com/voyager/api/graphql"
        f"?variables=(gameUrn:{encoded_urn})"
        f"&queryId=voyagerIdentityDashGameConnectionsEntities.{query_id}"
    )
    headers = {
        "accept": "application/json",
        "x-li-lang": "en_US",
        "x-restli-protocol-version": "2.0.0",
    }
    if csrf_token:
        headers["csrf-token"] = csrf_token
    try:
        resp = context.request.get(url, headers=headers)
        if resp.status != 200:
            logger.debug(f"Leaderboard API {resp.status} for {game_key}")
            return None
        data = resp.json()
        snapshot = (
            (data.get("data") or {})
            .get("identityDashGameConnectionsEntitiesByLeaderboardSnapshotV2")
        ) or {}
        metadata = snapshot.get("metadata") or {}
        return metadata.get("memberRanking") is not None
    except Exception as exc:
        logger.debug(f"Leaderboard check failed for {game_key}: {exc}")
        return None


def _extract_from_html(html: str, game_name: str, is_time: bool) -> tuple[Optional[str], Optional[str]]:
    """
    Parse the rendered page HTML and return (score, avg).
    Both may be None if the game wasn't played or the page structure changed.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract puzzle number from the page header, e.g. "Zip #389" → "389"
    number: Optional[str] = None
    subtext_el = soup.select_one(".pr-top__subtext")
    if subtext_el:
        m = re.search(r"#(\d+)", subtext_el.get_text())
        if m:
            number = m.group(1)

    for chiclet in soup.select(".pr-golden-chiclet"):
        subtext_el = chiclet.select_one(".pr-golden-chiclet__subtext")
        text_el    = chiclet.select_one(".pr-golden-chiclet__text")

        if not subtext_el or not text_el:
            continue

        subtext = subtext_el.get_text(strip=True)
        if not re.search(r"today.?s avg", subtext, re.IGNORECASE):
            continue

        # ── Average ───────────────────────────────────────────────────────────
        avg = re.sub(r"today.?s avg:\s*", "", subtext, flags=re.IGNORECASE).strip()

        # ── Score ─────────────────────────────────────────────────────────────
        raw = text_el.get_text(strip=True)

        if is_time:
            # Time games: expect "M:SS" or "MM:SS"
            m = re.search(r"\d+:\d{2}", raw)
            score = m.group(0) if m else None
        else:
            # Pinpoint: "Solved in 3"
            m = re.search(r"solved in (\d+)", raw, re.IGNORECASE)
            score = m.group(1) if m else None

        return score, avg, number

    # No chiclets — check for a loss ("Practice makes perfect!" headline)
    if not is_time:
        headline = soup.select_one(".pr-top__headline")
        if headline and re.search(r"practice makes perfect", headline.get_text(), re.IGNORECASE):
            logger.info(f"{game_name}: loss detected (no correct answer found in 5 guesses)")
            return "5", None, number

    return None, None, number


def _get_unplayed_names(page: Page) -> set[str]:
    """
    Parse the 'Play another game' section on a results page and return the
    set of game names that haven't been played today.

    Each list item contains a link whose raw href is a relative path like
    /games/crossclimb/ — we match that path against GAMES config entries.
    """
    soup = BeautifulSoup(page.content(), "html.parser")
    unplayed: set[str] = set()

    for item in soup.select(".pr-other-games__list-item"):
        link = item.select_one("a[href]")
        if not link:
            continue
        href_path = link["href"].rstrip("/")
        for game in GAMES:
            game_base_path = game["url"].split("linkedin.com")[-1].replace("/results/", "").rstrip("/")
            if href_path == game_base_path:
                unplayed.add(game["name"])
                break

    return unplayed


def _fetch_game(
    page: Page,
    game: dict,
    debug_dir: Optional[Path] = None,
    already_loaded: bool = False,
    game_urn: Optional[str] = None,
) -> GameResult:
    """Navigate to a single game results URL and extract score + avg.

    When game_urn is provided, appends ?gameUrn=<urn> to load a past puzzle's
    frozen results instead of today's live page.
    """
    name    = game["name"]
    url     = game["url"]
    is_time = game["is_time"]
    slug    = name.lower().replace(" ", "_")

    if game_urn:
        url = url + "?gameUrn=" + urllib.parse.quote(game_urn, safe="")

    logger.info(f"Fetching {name} ...")
    try:
        if not already_loaded:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)

        # If the page redirected away from /results/ the game hasn't been played yet
        if "/results/" not in page.url:
            logger.info(f"{name}: not yet completed today (redirected to {page.url})")
            return GameResult(name=name, score=None, avg=None, unplayed=True)

        # Wait for either the chiclet carousel (win) or the headline (loss)
        try:
            page.wait_for_selector(".pr-golden-chiclet, .pr-top__headline", timeout=15_000)
        except Exception:
            # Selector never appeared — still save debug output so we can see why
            if debug_dir:
                _save_debug(page, debug_dir, slug, chiclets_found=False)
            raise

        html = page.content()

        if debug_dir:
            _save_debug(page, debug_dir, slug, chiclets_found=True)

        score, avg, number = _extract_from_html(html, name, is_time)

        if score is None and avg is None:
            logger.warning(f"{name}: no score card found — game may not have been played today")
        else:
            num_str = f" #{number}" if number else ""
            logger.info(f"{name}{num_str}: score={score}, avg={avg}")

        return GameResult(name=name, score=score, avg=avg, number=number)

    except Exception as exc:
        logger.error(f"{name}: error fetching results — {exc}")
        return GameResult(name=name, score=None, avg=None, error=str(exc))


def _save_debug(page: Page, debug_dir: Path, slug: str, chiclets_found: bool) -> None:
    """Save a screenshot and HTML dump for a single game page."""
    debug_dir.mkdir(parents=True, exist_ok=True)

    screenshot_path = debug_dir / f"{slug}.png"
    html_path       = debug_dir / f"{slug}.html"

    page.screenshot(path=str(screenshot_path), full_page=True)
    html_path.write_text(page.content(), encoding="utf-8")

    # Log a quick summary of what chiclets were found in the HTML
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page.content(), "html.parser")
    chiclets = soup.select(".pr-golden-chiclet")
    texts = [c.get_text(separator=" | ", strip=True)[:80] for c in chiclets]

    logger.debug(f"  [{slug}] chiclets_found={chiclets_found}, count={len(chiclets)}")
    for t in texts:
        logger.debug(f"    · {t}")
    logger.info(f"  Debug files saved: {screenshot_path.name}, {html_path.name}")


def _norm_val(v) -> str:
    """Normalize a stored/parsed number or score to a comparable string."""
    return str(v).strip() if v is not None else ""


def _finalize_mismatch_reason(entry: dict, result: GameResult) -> Optional[str]:
    """
    Basic sanity check that a finalization results page is really for the puzzle
    we requested, guarding against LinkedIn silently serving a different results
    page for a stale/invalid gameUrn (which would corrupt the historical record).

    The gameUrn's puzzle number selects the puzzle server-side and is trusted;
    the puzzle number *displayed* on a past-puzzle results page is unreliable, so
    it is deliberately NOT compared. Instead we compare the recorded score, which
    is immutable once set — if the page's score differs from what we stored for
    this day, the wrong results were served. Returns None when the score matches,
    or a human-readable reason otherwise.
    """
    stored_score = _norm_val(entry.get("score"))
    got_score    = _norm_val(result.score)
    if got_score != stored_score:
        return f"stored score {stored_score or '?'} but page returned {got_score or '?'}"
    return None


def fetch_final_averages(
    target_games: dict,
    viewer_member_id: str,
    debug_dir: Optional[Path] = None,
    delay: float = 0.0,
) -> list[GameResult]:
    """
    Load past results pages via ?gameUrn= to capture frozen post-deadline averages.

    target_games: {game_key: {"number": "<puzzle_num>", ...}} from get_finalizable_games().
    Returns GameResult list; only avg (and error) are meaningful — score/number
    are not re-written by the caller.

    delay: seconds to pause (with jitter) before each game load after the first,
    to avoid tripping rate limiting when finalizing many games/days.
    """
    linkedin_state = get_linkedin_state()
    if linkedin_state is None:
        raise FileNotFoundError(
            "LinkedIn session not found. Run setup_auth.py first."
        )

    game_by_key = {g["key"]: g for g in GAMES}
    results: list[GameResult] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=linkedin_state,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        first_page = True
        fetches_done = 0

        for game_key, entry in target_games.items():
            game = game_by_key.get(game_key)
            if not game:
                logger.warning(f"fetch_final_averages: unknown game key {game_key!r}")
                continue
            number = entry.get("number")
            if not number:
                logger.warning(f"{game['name']}: no puzzle number stored — cannot build gameUrn")
                results.append(GameResult(name=game["name"], score=None, avg=None, error="no puzzle number"))
                continue

            if fetches_done:
                sleep_with_jitter(delay)

            game_urn = _build_game_urn(viewer_member_id, game_key, number)
            logger.info(f"Finalizing {game['name']} (puzzle #{number}) …")
            result = _fetch_game(page, game, debug_dir=debug_dir, game_urn=game_urn)
            fetches_done += 1

            # Sanity-check the loaded page against the recorded (immutable) score
            # before accepting its average — otherwise a mis-served page would
            # write a wrong average against this historical date. The displayed
            # puzzle number is unreliable for past puzzles, so it is not checked.
            if result.avg is not None:
                mismatch = _finalize_mismatch_reason(entry, result)
                if mismatch:
                    logger.error(
                        f"{game['name']}: score mismatch — {mismatch}. "
                        "Discarding average to protect the historical record."
                    )
                    result = GameResult(
                        name=game["name"], score=None, avg=None,
                        number=result.number, error="score mismatch",
                    )

            # Try to extract viewerMemberId from the first page we load as a
            # sanity-check / future-proof discovery path (result not used here).
            if first_page and result.error is None:
                first_page = False
                vmid_check = _try_extract_viewer_member_id(page.content())
                if vmid_check and vmid_check != viewer_member_id:
                    logger.warning(
                        f"viewer_member_id in config ({viewer_member_id[:8]}…) "
                        f"differs from page ({vmid_check[:8]}…) — "
                        "update viewer_member_id in config.json if gameUrns are wrong."
                    )

            results.append(result)

        browser.close()

    return results


def discover_voyager_ids() -> dict:
    """
    Open a short Playwright session and auto-discover both the viewer's LinkedIn
    member id and the connections-leaderboard queryId from a played game's
    results page. Its Voyager traffic carries both — no dev tools required.

    Returns {"viewer_member_id": <str|None>, "leaderboard_query_id": <str|None>}.
    Either value is None when the page couldn't be loaded or didn't surface it
    (e.g. the chosen game hasn't been played today).
    """
    linkedin_state = get_linkedin_state()
    if linkedin_state is None:
        return {"viewer_member_id": None, "leaderboard_query_id": None}

    try:
        layout_games = load_layout().included_game_names()
        game = next((g for g in GAMES if g["name"] in layout_games), GAMES[0])
    except Exception:
        game = GAMES[0]

    capture = _VoyagerIdCapture()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=linkedin_state,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        capture.attach(page)
        try:
            page.goto(game["url"], wait_until="domcontentloaded", timeout=20_000)
            if "/results/" in page.url:
                page.wait_for_selector(".pr-golden-chiclet, .pr-top__headline", timeout=10_000)
            # Let the connections-leaderboard request fire before reading.
            if capture.query_id is None:
                page.wait_for_timeout(2500)
            capture.scan_html(page.content())
        except Exception as exc:
            logger.debug(f"discover_voyager_ids page load: {exc}")
        finally:
            browser.close()

    return {"viewer_member_id": capture.member_id, "leaderboard_query_id": capture.query_id}


def discover_viewer_member_id() -> Optional[str]:
    """Backward-compatible shim: return only the viewer member id."""
    return discover_voyager_ids().get("viewer_member_id")


def fetch_all_scores(
    names: Optional[set[str]] = None,
    debug_dir: Optional[Path] = None,
    anchor_name: Optional[str] = None,
    leaderboard_query_id: Optional[str] = None,
    viewer_member_id: Optional[str] = None,
    results_data: Optional[dict] = None,
    discovered: Optional[dict] = None,
) -> list[GameResult]:
    """
    Launch a headless Playwright browser, restore the saved LinkedIn session,
    and scrape game results pages. Returns a list of GameResult objects in
    layout order (the games included in config.json); games excluded from
    the layout are never fetched or returned.

    names: optional set of game names to fetch. Layout-included games not in the
           set are returned as all-None placeholders so the list always covers
           every layout game. Pass None (default) to fetch every layout game.

    debug_dir: save a screenshot + HTML dump for every page visited when set.

    anchor_name: display name of a game to prefer as the anchor results page
                 when no already-recorded game is available. Typically the
                 game the user plays first each day, so its results page is
                 the most likely to be complete on a fresh day.

    leaderboard_query_id: when non-empty, make a parallel played/unplayed check
                          via the connections-leaderboard Voyager API for each
                          game and log the comparison against the anchor result.
                          Does not change any fetch decision — anchor method
                          remains authoritative. Empty or None disables this.

    viewer_member_id: LinkedIn member URN required for gameUrn construction when
                      leaderboard_query_id is provided. Read from config.json.

    results_data: full parsed results.json dict used to extrapolate today's
                  puzzle numbers for gameUrn construction. Pass None to skip
                  the leaderboard check even if query_id is set.

    discovered: optional dict the caller passes in to receive ids auto-captured
                from the anchor results-page load — "viewer_member_id" and
                "leaderboard_query_id". Both LinkedIn embeds in its own traffic,
                so this lets the caller seed/refresh config.json without dev
                tools. Values captured here are also used as fallbacks when the
                corresponding argument is empty (and, for the query id, to
                self-heal when LinkedIn rotates the hash).
    """
    linkedin_state = get_linkedin_state()
    if linkedin_state is None:
        raise FileNotFoundError(
            "LinkedIn session not found in the OS credential store.\n"
            "Run setup_auth.py first to log in and save your session."
        )

    results: list[GameResult] = []

    # The layout (config.json) is the source of truth for which games
    # the collector cares about. Restrict everything below to layout-included
    # games so excluded games (e.g. CrossClimb) are never fetched, printed, or
    # returned — even on a "fetch all" run where `names` is None.
    try:
        included_names = set(load_layout().included_game_names())
        layout_games = [g for g in GAMES if g["name"] in included_names]
    except Exception as exc:
        logger.warning(f"Could not read layout ({exc}); fetching all configured games.")
        layout_games = list(GAMES)
    if not layout_games:
        layout_games = list(GAMES)

    games_to_fetch = [g for g in layout_games if names is None or g["name"] in names]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context: BrowserContext = browser.new_context(
            storage_state=linkedin_state,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Passively harvest the viewer member id + leaderboard queryId from the
        # anchor page's own Voyager traffic (loaded just below). Lets us seed /
        # self-heal config.json without dev tools.
        id_capture = _VoyagerIdCapture()
        id_capture.attach(page)

        # ── Determine unplayed games via a completed results page ─────────────
        # Anchor cascade (first match wins):
        #   1. Any game already recorded in today's row (not in games_to_fetch)
        #      — guaranteed complete, so the unplayed-list widget loads.
        #   2. The caller-provided anchor_name, when supplied. Intended for
        #      "the game the user typically plays first", which is the most
        #      likely to be complete on a fresh day with nothing yet recorded.
        #   3. The first game in games_to_fetch as a last resort.
        fetch_names = {g["name"] for g in games_to_fetch}
        already_recorded = next(
            (g for g in layout_games if g["name"] not in fetch_names), None
        )
        configured_anchor = (
            next((g for g in layout_games if g["name"] == anchor_name), None)
            if anchor_name else None
        )
        anchor = already_recorded or configured_anchor or games_to_fetch[0]
        logger.info(f"Loading anchor results page ({anchor['name']}) to check unplayed games …")
        page.goto(anchor["url"], wait_until="domcontentloaded", timeout=20_000)

        anchor_played = "/results/" in page.url
        if anchor_played:
            try:
                page.wait_for_selector(".pr-other-games__list-item", timeout=10_000)
            except Exception:
                logger.debug("No '.pr-other-games__list-item' found — all games may be complete")
            unplayed = _get_unplayed_names(page)
            if unplayed:
                logger.info(f"Not yet played today: {', '.join(sorted(unplayed))}")
        else:
            # Anchor game itself isn't complete — can't read the list
            logger.debug(f"Anchor game ({anchor['name']}) not yet completed — skipping unplayed check")
            unplayed = set()

        # ── Timer-safety guard: bail out if the anchor itself is unplayed ─────
        # When the anchor's results page redirected away from /results/, the
        # anchor game hasn't been played yet, so the unplayed-list widget never
        # loaded and we don't know which games are safe to open. Probing each
        # game individually would navigate to its page and can start the timer
        # on an unplayed *timed* game (see SETUP.md "Anchor Games"). To stay
        # timer-safe we stop here and report every to-fetch game as unplayed —
        # only the anchor page itself was loaded. A later run, once the anchor
        # has been played, collects everything normally. Picking a non-timed
        # anchor (e.g. Pinpoint) makes even that single anchor load risk-free.
        if not anchor_played:
            logger.warning(
                f"Anchor game ({anchor['name']}) has not been played yet today — "
                "skipping all game probes to avoid starting timers on unplayed "
                "games. Nothing collected this run; re-run after playing the anchor."
            )
            browser.close()
            fetched = {
                g["name"]: GameResult(name=g["name"], score=None, avg=None, unplayed=True)
                for g in games_to_fetch
            }
            return [
                fetched.get(g["name"], GameResult(name=g["name"], score=None, avg=None))
                for g in layout_games
            ]

        # ── Report ids auto-captured from the anchor load back to the caller ──
        # (member id + leaderboard queryId). The caller persists these to
        # config.json — seeding them on first run and refreshing the queryId
        # whenever LinkedIn rotates its hash.
        if discovered is not None:
            if id_capture.member_id:
                discovered["viewer_member_id"] = id_capture.member_id
            if id_capture.query_id:
                discovered["leaderboard_query_id"] = id_capture.query_id

        # Effective ids: prefer the explicit argument, fall back to what the
        # anchor load surfaced, so a fresh config (empty values) still works.
        eff_member_id = viewer_member_id or id_capture.member_id
        eff_query_id = leaderboard_query_id or id_capture.query_id

        # ── Parallel leaderboard played/unplayed check (experimental) ────────
        # Calls the connections-leaderboard Voyager API for each game we're
        # about to fetch and logs the result alongside the anchor-based decision.
        # Purely observational — does not change any fetch decision below.
        if eff_query_id and eff_member_id and results_data is not None:
            today = date.today()
            csrf_token = _voyager_csrf_token(context)
            if not csrf_token:
                logger.debug("No JSESSIONID cookie — leaderboard check will be unavailable")
            for game in games_to_fetch:
                game_key = game["key"]
                puzzle_num = _extrapolate_puzzle_number(game_key, today, results_data)
                if puzzle_num is None:
                    logger.debug(f"{game['name']}: no prior puzzle number — leaderboard check skipped")
                    continue
                lb_played = _check_played_leaderboard(
                    context, game_key, puzzle_num, eff_member_id, eff_query_id, csrf_token
                )
                anchor_says = "unplayed" if game["name"] in unplayed else "played"
                if lb_played is None:
                    lb_label = "unavailable"
                    match_marker = ""
                elif lb_played:
                    lb_label = "played"
                    match_marker = " ✓" if anchor_says == "played" else " *** MISMATCH ***"
                else:
                    lb_label = "unplayed"
                    match_marker = " ✓" if anchor_says == "unplayed" else " *** MISMATCH ***"
                logger.info(
                    f"{game['name']}: anchor={anchor_says}, leaderboard={lb_label}{match_marker}"
                )

        # ── Fetch each game that needs data and isn't known-unplayed ──────────
        # Process the anchor first while its results page (loaded above for the
        # unplayed check) is still the one in the browser. Otherwise an earlier
        # navigation would leave a different game's results page loaded, and the
        # `already_loaded` shortcut below — which only checks that *some*
        # /results/ page is open — would scrape that wrong page for the anchor.
        fetch_order = sorted(games_to_fetch, key=lambda g: g["name"] != anchor["name"])
        fetched: dict[str, GameResult] = {}
        for game in fetch_order:
            if game["name"] in unplayed:
                logger.info(f"{game['name']}: not yet played today — skipping")
                fetched[game["name"]] = GameResult(name=game["name"], score=None, avg=None, unplayed=True)
            elif game["name"] == anchor["name"] and "/results/" in page.url:
                # Anchor page is already loaded — extract directly without re-navigating
                fetched[game["name"]] = _fetch_game(page, game, debug_dir=debug_dir, already_loaded=True)
            else:
                fetched[game["name"]] = _fetch_game(page, game, debug_dir=debug_dir)

        browser.close()

    # Rebuild in layout order; games not in fetch list get all-None placeholders.
    # Excluded games are absent from layout_games, so they never appear here.
    for game in layout_games:
        results.append(fetched.get(game["name"], GameResult(name=game["name"], score=None, avg=None)))

    return results
