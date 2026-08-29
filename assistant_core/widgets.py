"""Informational HUD widgets - stocks, tech news, weather. Purely for the
web UI's sidebar; not LLM-visible tools. Each has its own cache TTL since
they update at very different natural rates (stocks change by the
second, weather by the half hour) and none of them warrant hitting their
upstream API on every single frontend poll.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import httpx

from assistant_core.config import get_config

STOCKS_CACHE_SECONDS = 60
NEWS_CACHE_SECONDS = 600
WEATHER_CACHE_SECONDS = 1800

_stocks_cache: dict = {"value": None, "ts": 0.0}
_news_cache: dict = {"value": None, "ts": 0.0}
_weather_cache: dict = {"value": None, "geocoded": None, "ts": 0.0}

_WEATHER_CODES = {
    0: "Clear sky", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Light showers", 81: "Showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Severe thunderstorm w/ hail",
}


async def get_stocks() -> list[dict]:
    now = time.monotonic()
    if _stocks_cache["value"] is not None and now - _stocks_cache["ts"] < STOCKS_CACHE_SECONDS:
        return _stocks_cache["value"]

    symbols = get_config().widgets.stock_symbols
    results = []
    async with httpx.AsyncClient(timeout=5.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for symbol in symbols:
            try:
                resp = await client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"interval": "1d", "range": "1d"},
                )
                meta = resp.json()["chart"]["result"][0]["meta"]
                price = meta["regularMarketPrice"]
                prev_close = meta["chartPreviousClose"]
                change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0.0
                results.append(
                    {
                        "symbol": symbol,
                        "price": round(price, 2),
                        "change_percent": round(change_pct, 2),
                    }
                )
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ZeroDivisionError):
                results.append({"symbol": symbol, "price": None, "change_percent": None})

    _stocks_cache["value"] = results
    _stocks_cache["ts"] = now
    return results


async def get_news() -> list[dict]:
    now = time.monotonic()
    if _news_cache["value"] is not None and now - _news_cache["ts"] < NEWS_CACHE_SECONDS:
        return _news_cache["value"]

    feeds = get_config().widgets.news_feeds
    items: list[dict] = []
    async with httpx.AsyncClient(timeout=5.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for feed_url in feeds:
            try:
                resp = await client.get(feed_url)
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item")[:8]:
                    title = item.findtext("title", "").strip()
                    link = item.findtext("link", "").strip()
                    if title:
                        items.append({"title": title, "link": link})
            except (httpx.HTTPError, ET.ParseError):
                continue

    items = items[:10]
    _news_cache["value"] = items
    _news_cache["ts"] = now
    return items


async def get_weather() -> dict | None:
    now = time.monotonic()
    if _weather_cache["value"] is not None and now - _weather_cache["ts"] < WEATHER_CACHE_SECONDS:
        return _weather_cache["value"]

    location = get_config().widgets.weather_location
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            if _weather_cache["geocoded"] is None:
                geo_resp = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": location, "count": 1},
                )
                results = geo_resp.json().get("results") or []
                if not results:
                    return None
                _weather_cache["geocoded"] = {
                    "lat": results[0]["latitude"],
                    "lon": results[0]["longitude"],
                    "name": results[0]["name"],
                    "country": results[0].get("country", ""),
                }

            geo = _weather_cache["geocoded"]
            wx_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": geo["lat"],
                    "longitude": geo["lon"],
                    "current": "temperature_2m,weather_code,relative_humidity_2m",
                    "temperature_unit": "celsius",
                },
            )
            current = wx_resp.json()["current"]
            value = {
                "location": f"{geo['name']}, {geo['country']}",
                "temperature_c": current["temperature_2m"],
                "humidity_percent": current["relative_humidity_2m"],
                "condition": _WEATHER_CODES.get(current["weather_code"], "Unknown"),
            }
        except (httpx.HTTPError, KeyError, IndexError, TypeError):
            return _weather_cache["value"]

    _weather_cache["value"] = value
    _weather_cache["ts"] = now
    return value
