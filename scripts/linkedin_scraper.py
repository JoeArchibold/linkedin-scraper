"""
LinkedIn Games scraper using Playwright + BeautifulSoup.

Loads a saved browser state (cookies) so no interactive login is needed
on normal runs. Call setup_auth.py once to save the state in the OS credential
store.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page, BrowserContext

from auth_store import (
    LINKEDIN_STATE_KEY,
    get_linkedin_state,
    import_json_file_if_missing,
)
from config import GAMES, LINKEDIN_STATE_FILE

logger = logging.getLogger(__name__)


@dataclass
class GameResult:
    name: str
    score: Optional[str]   # "0:17" / "1:23" for time games, "3" for Pinpoint
    avg: Optional[str]     # same format as score
    number: Optional[str] = None  # puzzle number, e.g. "389"
    error: Optional[str] = None
    unplayed: bool = False  # True when the game hasn't been played yet today


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


def _fetch_game(page: Page, game: dict, debug_dir: Optional[Path] = None, already_loaded: bool = False) -> GameResult:
    """Navigate to a single game results URL and extract score + avg."""
    name    = game["name"]
    url     = game["url"]
    is_time = game["is_time"]
    slug    = name.lower().replace(" ", "_")

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


def fetch_all_scores(
    names: Optional[set[str]] = None,
    debug_dir: Optional[Path] = None,
    anchor_name: Optional[str] = None,
) -> list[GameResult]:
    """
    Launch a headless Playwright browser, restore the saved LinkedIn session,
    and scrape game results pages. Returns a list of GameResult objects in the
    same order as config.GAMES.

    names: optional set of game names to fetch. Games not in the set are
           returned as all-None results so the list length is always len(GAMES).
           Pass None (default) to fetch every game.

    debug_dir: save a screenshot + HTML dump for every page visited when set.

    anchor_name: display name of a game to prefer as the anchor results page
                 when no already-recorded game is available. Typically the
                 game the user plays first each day, so its results page is
                 the most likely to be complete on a fresh day.
    """
    imported = import_json_file_if_missing(LINKEDIN_STATE_KEY, LINKEDIN_STATE_FILE)
    if imported:
        logger.info("Imported legacy LinkedIn session file into the OS credential store.")

    linkedin_state = get_linkedin_state()
    if linkedin_state is None:
        raise FileNotFoundError(
            "LinkedIn session not found in the OS credential store.\n"
            "Run setup_auth.py first to log in and save your session."
        )

    results: list[GameResult] = []
    games_to_fetch = [g for g in GAMES if names is None or g["name"] in names]

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
            (g for g in GAMES if g["name"] not in fetch_names), None
        )
        configured_anchor = (
            next((g for g in GAMES if g["name"] == anchor_name), None)
            if anchor_name else None
        )
        anchor = already_recorded or configured_anchor or games_to_fetch[0]
        logger.info(f"Loading anchor results page ({anchor['name']}) to check unplayed games …")
        page.goto(anchor["url"], wait_until="domcontentloaded", timeout=20_000)

        if "/results/" in page.url:
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

        # ── Fetch each game that needs data and isn't known-unplayed ──────────
        fetched: dict[str, GameResult] = {}
        for game in games_to_fetch:
            if game["name"] in unplayed:
                logger.info(f"{game['name']}: not yet played today — skipping")
                fetched[game["name"]] = GameResult(name=game["name"], score=None, avg=None, unplayed=True)
            elif game["name"] == anchor["name"] and "/results/" in page.url:
                # Anchor page is already loaded — extract directly without re-navigating
                fetched[game["name"]] = _fetch_game(page, game, debug_dir=debug_dir, already_loaded=True)
            else:
                fetched[game["name"]] = _fetch_game(page, game, debug_dir=debug_dir)

        browser.close()

    # Rebuild in GAMES order; games not in fetch list get all-None placeholders
    for game in GAMES:
        results.append(fetched.get(game["name"], GameResult(name=game["name"], score=None, avg=None)))

    return results
