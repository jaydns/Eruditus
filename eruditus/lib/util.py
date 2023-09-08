import io
import json
import logging
import os
import re
import urllib.parse
import warnings
from datetime import datetime, timezone
from hashlib import md5
from logging import Logger
from string import ascii_lowercase, digits
from typing import Any, Optional, Type, TypeVar

import discord
import matplotlib.pyplot as plt
from aiohttp import ClientResponse
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
from markdownify import markdownify as html2md
from pydantic import TypeAdapter, ValidationError

from lib.platforms.abc import ChallengeFile, TeamScoreHistory

T = TypeVar("T")
logger = logging.getLogger("eruditus.util")

# "The input looks more like a filename than a markup" warnings
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


def get_local_time() -> datetime:
    """Return offset aware local time.

    Returns:
        Offset aware datetime object.
    """
    local_timezone = datetime.now(timezone.utc).astimezone().tzinfo
    return datetime.now(local_timezone)


def truncate(text: str, max_len: int = 1024) -> str:
    """Truncate a paragraph to a specific length.

    Args:
        text: The paragraph to truncate.
        max_len: The maximum length of the paragraph.

    Returns:
        The truncated paragraph.
    """
    etc = "\n[…]"
    return (
        f"{text[:max_len - len(etc)]}{etc}" if len(text) > max_len - len(etc) else text
    )


def sanitize_channel_name(name: str) -> str:
    """Filter out characters that aren't allowed by Discord for guild channels.

    Args:
        name: Channel name.

    Returns:
        Sanitized channel name.
    """
    whitelist = ascii_lowercase + digits + "-_"
    name = name.lower().replace(" ", "-")

    for char in name:
        if char not in whitelist:
            name = name.replace(char, "")

    while "--" in name:
        name = name.replace("--", "-")

    return name


def derive_colour(role_name: str) -> int:
    """Derive a colour for the CTF role by taking its MD5 hash and using the first 3
    bytes as the colour.

    Args:
        role_name: Name of the role we wish to set a colour for.

    Returns:
        An integer representing an RGB colour.
    """
    return int(md5(role_name.encode()).hexdigest()[:6], 16)


def setup_logger(name: str, level: int) -> Logger:
    """Set up logging.

    Args:
        name: Logger name.
        level: Logging level.

    Returns:
        The logger.
    """
    log_formatter = logging.Formatter(
        "[{asctime}] [{levelname:<8}] {name}: {message}", "%Y-%m-%d %H:%M:%S", style="{"
    )

    result = logging.getLogger(name)
    result.setLevel(level)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_formatter)

    result.addHandler(stream_handler)
    return result


def in_range(value: int, minimal: int, maximum: int) -> bool:
    """Check whether number is in desired range.

    Args:
        value: The value that is going to be checked.
        minimal: Min value.
        maximum: Max value.

    Returns:
        True or false.
    """
    return minimal <= value <= maximum


def is_empty_string(value: Optional[str]) -> bool:
    """Check whether a string is empty.

    Args:
        value: The string that is going to be checked.

    Returns:
        True if the string is empty or None, False otherwise.

    Raises:
        TypeError: if `value` is of type other than `None` or `str`.
    """
    if value is not None and not isinstance(value, str):
        raise TypeError("Value must be either None or a string")
    return value is None or value.strip() == ""


def extract_filename_from_url(url: str) -> str:
    """Extract a filename from a URL.

    Args:
        The URL to extract the filename from.

    Returns:
        The filename.
    """
    return os.path.basename(urllib.parse.urlparse(url).path)


def html_to_markdown(description: Optional[str]) -> Optional[str]:
    """Convert HTML content to Markdown.

    Args:
        The HTML content.

    Returns:
        Converted result.
    """
    if description is None:
        return None

    # Convert to markdown.
    md = html2md(
        description,
        heading_style="atx",
        escape_asterisks=False,
        escape_underscores=False,
    )

    # Remove all images.
    md = re.sub(r'[^\S\r\n]*!\[[^\]]*\]\((.*?)\s*("(?:.*[^"])")?\s*\)\s*', "", md)

    # Remove multilines.
    md = re.sub(r"\n+", "\n", md)

    return md


def convert_attachment_url(url: str, base_url: Optional[str]) -> str:
    """Convert attachment URL to an absolute URL.

    Args:
        url: The attachment url.
        base_url: Domain base url.

    Returns:
        Absolute url.
    """
    if not url.startswith("http") and base_url:
        url = f'{base_url.rstrip("/")}/{url.lstrip("/")}'

    return url


def parse_attachment(url: str, base_url: Optional[str]) -> ChallengeFile:
    """Convert attachment URL to a ChallengeFile item.

    Args:
        url: The attachment url.
        base_url: Domain base url.

    Returns:
        Converted file.
    """
    return ChallengeFile(
        url=convert_attachment_url(url, base_url),
        name=extract_filename_from_url(url),
    )


def extract_images_from_html(
    description: Optional[str], base_url: Optional[str] = None
) -> Optional[list[ChallengeFile]]:
    """Extract `img` tags from the HTML description.

    Args:
        description: The HTMl content.
        base_url: Domain base url.

    TODO:
        Add markdown support.

    Returns:
        Converted files.
    """
    if not description:
        return None

    result = []

    for img in BeautifulSoup(description, "html.parser").findAll("img"):
        src: Optional[str] = img.get("src")
        if not src:
            continue

        result.append(parse_attachment(src, base_url))

    return result


def strip_url_components(url: str) -> str:
    """Strip the path, query parameters and fragments from a URL.

    Args:
        The URL to parse.

    Returns:
        The base URL.
    """
    parsed_url = urllib.parse.urlparse(url)
    return f"{parsed_url.scheme}://{parsed_url.netloc}"


def extract_rctf_team_token(invite_url: str) -> Optional[str]:
    """Extract the rCTF team token from an invite URL.

    Args:
        The rCTF invite URL (e.g., https://rctf.example.com/login?token=<token>).

    Returns:
        The team token.
    """
    parsed_url = urllib.parse.urlparse(invite_url)
    params = urllib.parse.parse_qs(parsed_url.query)
    if not (team_token := params.get("token")):
        return None

    return team_token[0]


def make_form_field_config(name: str, config: dict) -> dict:
    """Generate configuration for a form field.

    Args:
        name: The field name (e.g., username, password, etc.).
        config: The form configuration (label, placeholder, etc.), for a full list, see
            the arguments of `discord.ui.TextInput`.

    Returns:
        A dictionary containing the field configuration.
    """
    max_length = 128
    match name:
        case "email":
            label, placeholder = "Email", "Enter your email..."
        case "username":
            label, placeholder = "Username", "Enter your username..."
        case "password":
            label, placeholder = "Password", "Enter your password..."
        case "invite":
            label, placeholder, max_length = (
                "Invite link",
                "Enter your team invite URL...",
                512,
            )
        case "token":
            label, placeholder, max_length = (
                "Token",
                "Enter your team token...",
                256,
            )

    return {
        "label": config.get("label", label),
        "placeholder": config.get("placeholder", placeholder),
        "required": config.get("required", True),
        "max_length": config.get("max_length", max_length),
        "style": config.get("style", discord.TextStyle.short),
    }


async def deserialize_response(
    response: ClientResponse, model: Type[T], suppress_warnings: bool = False
) -> Optional[T]:
    """Validate response status code and JSON content.

    Args:
        response: The HTTP response.
        model: The pydantic model used to validate the JSON response.
        suppress_warnings: No warnings would be printed if set to true.

    Returns:
        A deserialized response if the response is valid, None otherwise.
    """
    response_ranges: list[list[int]] = [
        [200, 299],  # ok
        [400, 499],  # client-side errors
    ]

    valid_status_code: bool = False
    for response_range in response_ranges:
        valid_status_code |= in_range(response.status, *response_range)

    if not valid_status_code:
        return None

    response_json: dict[str, Any] = await response.json()

    try:
        return TypeAdapter(model).validate_python(response_json)
    except ValidationError as e:
        if not suppress_warnings:
            logger.warning(
                "Could not validate response data using the %s model:\n%s\nErrors - %s",
                model.__name__,
                json.dumps(response_json, indent=2),
                str(e),
            )
        return None


def plot_scoreboard(
    data: list[TeamScoreHistory], fig_size: tuple = (15, 6)
) -> io.BytesIO:
    """Plot scoreboard.

    Args:
        data: A list where each element is a struct containing:
            - The team name (used as the label in the graph).
            - The timestamps of each solve (as `datetime` objects, these will fill the
                x-axis).
            - The number of points at each instant (these will fill the y-axis).
        fig_size: The figure size.

    Returns:
        A BytesIO buffer containing the saved figure data in bytes.
    """

    # Using an actual color instead of a transparent background in order for the text
    # to be visible in light theme as well.
    background_color: str = "#313338"

    # Creating the new figure
    fig: plt.Figure = plt.figure(
        figsize=fig_size, facecolor=background_color, layout="tight"
    )

    # Applying background color to the axes
    axes = fig.subplots()
    for axe in [axes] if not isinstance(axes, list) else axes:
        axe.set_facecolor(background_color)

    # Obtaining current axes and applying the title
    gca: plt.Subplot = fig.gca()
    gca.set_title(
        label=f"Top {len(data)} Teams", fontdict={"weight": "bold", "color": "white"}
    )

    for team in data:
        kw = {}
        if team.is_me:
            kw["zorder"] = len(data) + 1  # bring our team to the front

        # Creating a new plot item with the X axis set to time
        # and the Y axis set to score
        gca.plot(
            [x.time for x in team.history],
            [x.score for x in team.history],
            label=team.name,
            **kw,
        )

    # Applying grid and legend style
    gca.grid(color="gray", linestyle="dashed", alpha=0.5)
    gca.legend(loc="best")

    # Applying x tick labels styles
    for label in gca.get_xticklabels(minor=False):
        label.set(rotation=45, color="white")

    # Applying y tick labels style
    for label in gca.get_yticklabels(minor=False):
        label.set(color="white")

    # Applying spine colors
    for highlighted_spine in ["bottom", "left"]:
        gca.spines[highlighted_spine].set_color("white")

    # Making the top/right spines invisible
    for invisible_spine in ["top", "right"]:
        gca.spines[invisible_spine].set_visible(False)

    # Saving the result and closing the figure object
    result = io.BytesIO()
    fig.savefig(result, bbox_inches="tight")
    plt.close(fig)

    # Reset buffer pos and returning it
    result.seek(0)
    return result
