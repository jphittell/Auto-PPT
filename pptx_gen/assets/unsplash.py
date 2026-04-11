"""Unsplash-backed stock image sourcing for the assets stage."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError


logger = logging.getLogger(__name__)

_UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
_UTM_SOURCE = "auto-ppt"
_UTM_MEDIUM = "referral"


class UnsplashPhoto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    download_url: str = Field(min_length=1)
    photographer_name: str = Field(min_length=1)
    photographer_url: str = Field(min_length=1)
    cached_path: str = Field(min_length=1)


class _UnsplashUserLinks(BaseModel):
    model_config = ConfigDict(extra="ignore")

    html: str = Field(min_length=1)


class _UnsplashUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    links: _UnsplashUserLinks


class _UnsplashPhotoLinks(BaseModel):
    model_config = ConfigDict(extra="ignore")

    html: str = Field(min_length=1)
    download_location: str = Field(min_length=1)


class _UnsplashSearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    links: _UnsplashPhotoLinks
    user: _UnsplashUser


class _UnsplashSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_UnsplashSearchResult] = Field(default_factory=list)


class _UnsplashDownloadResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = Field(min_length=1)


class UnsplashAssetSource:
    """Resolve search queries to locally cached Unsplash images."""

    def __init__(
        self,
        *,
        cache_dir: str | Path,
        access_key: str | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        _load_local_env()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.access_key = access_key if access_key is not None else os.getenv("UNSPLASH_ACCESS_KEY")
        self.timeout_s = timeout_s

    def fetch_photo(self, query: str) -> UnsplashPhoto | None:
        normalized_query = query.strip()
        if not normalized_query:
            logger.warning("Unsplash lookup skipped because the query was empty")
            return None
        if not self.access_key:
            logger.warning("UNSPLASH_ACCESS_KEY is not set; skipping Unsplash lookup for query '%s'", normalized_query)
            return None

        try:
            search_response = _UnsplashSearchResponse.model_validate(
                self._get_json(
                    _UNSPLASH_SEARCH_URL,
                    params={"query": normalized_query, "page": 1, "per_page": 10, "orientation": "landscape"},
                )
            )
            if not search_response.results:
                logger.warning("Unsplash returned no results for query '%s'", normalized_query)
                return None

            best_match = search_response.results[0]
            download_response = _UnsplashDownloadResponse.model_validate(
                self._get_json(best_match.links.download_location)
            )
            image_bytes, content_type = self._download_binary(download_response.url)
        except (HTTPError, URLError, OSError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Unsplash lookup failed for query '%s': %s", normalized_query, exc)
            return None

        extension = _extension_for_asset(download_response.url, content_type)
        cache_key = hashlib.sha256(image_bytes).hexdigest()
        cached_path = self.cache_dir / f"unsplash-{cache_key}{extension}"
        if not cached_path.exists():
            cached_path.write_bytes(image_bytes)

        return UnsplashPhoto(
            url=_with_unsplash_referral(best_match.links.html),
            download_url=download_response.url,
            photographer_name=best_match.user.name,
            photographer_url=_with_unsplash_referral(best_match.user.links.html),
            cached_path=str(cached_path),
        )

    def _get_json(self, url: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
        request_url = url
        if params:
            request_url = f"{url}?{urlencode(params)}"
        request = Request(request_url, headers=self._api_headers())
        with urlopen(request, timeout=self.timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    def _download_binary(self, url: str) -> tuple[bytes, str | None]:
        request = Request(url, headers={"User-Agent": "auto-ppt"})
        with urlopen(request, timeout=self.timeout_s) as response:
            payload = response.read()
            return payload, response.headers.get_content_type()

    def _api_headers(self) -> dict[str, str]:
        if not self.access_key:
            return {"Accept-Version": "v1"}
        return {
            "Accept-Version": "v1",
            "Authorization": f"Client-ID {self.access_key}",
        }


def _load_local_env() -> None:
    dotenv_path = find_dotenv(filename=".env", usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)


def _with_unsplash_referral(url: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["utm_source"] = _UTM_SOURCE
    query["utm_medium"] = _UTM_MEDIUM
    return urlunparse(parsed._replace(query=urlencode(query)))


def _extension_for_asset(url: str, content_type: str | None) -> str:
    if content_type:
        guessed = mimetypes.guess_extension(content_type)
        if guessed:
            return ".jpg" if guessed == ".jpe" else guessed
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix:
        return suffix
    return ".jpg"
