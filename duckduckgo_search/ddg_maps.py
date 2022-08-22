import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from time import sleep

import requests
from requests import ConnectionError

from .utils import _normalize, _save_csv, _save_json, get_vqd, headers, session

logger = logging.getLogger(__name__)


@dataclass
class MapsResult:
    """Dataclass for ddg_maps search results"""

    title = None
    address = None
    country_code = None
    latitude = None
    longitude = None
    url = None
    desc = None
    phone = None
    image = None
    source = None
    links = None
    hours = None


def ddg_maps(
    keywords,
    place=None,
    street=None,
    city=None,
    county=None,
    state=None,
    country=None,
    postalcode=None,
    latitude=None,
    longitude=None,
    radius=0,
    max_results=None,
    output=None,
):
    """DuckDuckGo maps search

    Args:
        keywords: keywords for query
        place: simplified search - if set, the other parameters are not used. Defaults to None.
        street: house number/street. Defaults to None.
        city: city of search. Defaults to None.
        county: county of search. Defaults to None.
        state: state of search. Defaults to None.
        country: country of search. Defaults to None.
        postalcode: postalcode of search. Defaults to None.
        latitude: geographic coordinate that specifies the north–south position. Defaults to None.
        longitude: geographic coordinate that specifies the east–west position;
            if latitude and longitude are set, the other parameters are not used. Defaults to None.
        radius: expand the search square by the distance in kilometers. Defaults to 0.
        max_results: maximum number of results. Defaults to None.
        output: csv, json, print. Defaults to None.

    Returns:
        DuckDuckGo maps search results
    """

    if not keywords:
        return None

    # get vqd
    vqd = get_vqd(keywords)
    if not vqd:
        return
    sleep(0.75)

    # if longitude and latitude are specified, skip the request about bbox to the nominatim api
    if latitude and longitude:
        lat_t = Decimal(latitude.replace(",", "."))
        lat_b = Decimal(latitude.replace(",", "."))
        lon_l = Decimal(longitude.replace(",", "."))
        lon_r = Decimal(longitude.replace(",", "."))
        if radius == 0:
            radius = 1
    # otherwise request about bbox to nominatim api
    else:
        if place:
            params = {
                "q": place,
                "polygon_geojson": "0",
                "format": "jsonv2",
            }
        else:
            params = {
                "street": street,
                "city": city,
                "county": county,
                "state": state,
                "country": country,
                "postalcode": postalcode,
                "polygon_geojson": "0",
                "format": "jsonv2",
            }
        try:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search.php",
                params=params,
                headers=headers,
            )
            logger.info(f"{resp.status_code} {resp.url}")
            coordinates = resp.json()[0]["boundingbox"]
            lat_t, lon_l = Decimal(coordinates[1]), Decimal(coordinates[2])
            lat_b, lon_r = Decimal(coordinates[0]), Decimal(coordinates[3])
        except ConnectionError:
            logger.error("Connection Error.")
            return
        except Exception:
            logger.exception("Exception.", exc_info=True)
            return

    # if a radius is specified, expand the search square
    lat_t += Decimal(radius) * Decimal(0.008983)
    lat_b -= Decimal(radius) * Decimal(0.008983)
    lon_l -= Decimal(radius) * Decimal(0.008983)
    lon_r += Decimal(radius) * Decimal(0.008983)
    print(f"bbox coordinates\n{lat_t} {lon_l}\n{lat_b} {lon_r}")

    # сreate a queue of search squares (bboxes)
    work_bboxes = deque()
    work_bboxes.append((lat_t, lon_l, lat_b, lon_r))

    # bbox iterate
    results, cache = [], set()
    stop_find = False
    while work_bboxes and not stop_find:
        lat_t, lon_l, lat_b, lon_r = work_bboxes.pop()
        params = {
            "q": keywords,
            "vqd": vqd,
            "tg": "maps_places",
            "rt": "D",
            "mkexp": "b",
            "wiki_info": "1",
            "is_requery": "1",
            "bbox_tl": f"{lat_t},{lon_l}",
            "bbox_br": f"{lat_b},{lon_r}",
            "strict_bbox": "1",
        }
        page_data = None
        try:
            resp = session.get("https://duckduckgo.com/local.js", params=params)
            logger.info(f"{resp.status_code} {resp.url}")
            page_data = resp.json()["results"]
        except ConnectionError:
            logger.error("Connection Error.")
            break
        except Exception:
            logger.exception("Exception.", exc_info=True)
            break

        if not page_data:
            break

        for res in page_data:
            result = MapsResult()
            result.title = res["name"]
            result.address = res["address"]
            if result.title + result.address in cache:
                continue
            else:
                cache.add(result.title + result.address)
                result.country_code = res["country_code"]
                result.url = res["website"]
                result.phone = res["phone"]
                result.latitude = res["coordinates"]["latitude"]
                result.longitude = res["coordinates"]["longitude"]
                result.source = _normalize(res["url"])
                if res["embed"]:
                    result.image = res["embed"].get("image", "")
                    result.links = res["embed"].get("third_party_links", "")
                    result.desc = res["embed"].get("description", "")
                result.hours = res["hours"]
                results.append(result.__dict__)
                if max_results and len(results) >= max_results:
                    stop_find = True
                    break

        # divide the square into 4 parts and add to the queue
        if len(page_data) >= 15:
            lat_middle = (lat_t + lat_b) / 2
            lon_middle = (lon_l + lon_r) / 2
            bbox1 = (lat_t, lon_l, lat_middle, lon_middle)
            bbox2 = (lat_t, lon_middle, lat_middle, lon_r)
            bbox3 = (lat_middle, lon_l, lat_b, lon_middle)
            bbox4 = (lat_middle, lon_middle, lat_b, lon_r)
            work_bboxes.extendleft([bbox1, bbox2, bbox3, bbox4])

        print(f"Found {len(results)}")
        sleep(0.2)

    # output
    keywords = keywords.replace('"', "'")
    if output == "csv":
        _save_csv(
            f"ddg_maps_{keywords}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            results,
        )
    elif output == "json":
        _save_json(
            f"ddg_maps_{keywords}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            results,
        )
    elif output == "print":
        for i, result in enumerate(results, start=1):
            print(f"{i}.", json.dumps(result, ensure_ascii=False, indent=2))
            input()
    return results
