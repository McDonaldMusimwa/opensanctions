import os
import time
import string
from itertools import count
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from requests.exceptions import HTTPError, RequestException, RetryError

from zavod import Context
from zavod import helpers as h


class AbortCrawl(Exception):
    pass


API_KEY = os.environ.get("OPENSANCTIONS_COH_API_KEY", "")
AUTH = (API_KEY, "")
SEARCH_URL = (
    "https://api.company-information.service.gov.uk/search/disqualified-officers"
)
# SEARCH_URL = "https://api-sandbox.company-information.service.gov.uk/search/disqualified-officers"
API_URL = "https://api.company-information.service.gov.uk/"
WEB_URL = "https://find-and-update.company-information.service.gov.uk/register-of-disqualifications/A"
SLEEP = 315


def http_get(
    context: Context,
    url,
    params: Optional[Dict[str, Any]] = None,
    cache_days: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    for attempt in count(1):
        try:
            return context.fetch_json(
                url,
                params=params,
                auth=AUTH,
                cache_days=cache_days,
            )
        except RetryError as rer:
            if attempt > 5:
                raise AbortCrawl()
            context.log.warn(f"Rate limit exceeded ({rer}), sleeping {SLEEP}s...")
            time.sleep(SLEEP)
        except HTTPError as err:
            if err.response.status_code == 429 or "429" in str(err):
                if attempt > 5:
                    raise AbortCrawl()
                context.log.warn(
                    f"Rate limit exceeded, sleeping {SLEEP}s...",
                    error=err.response.text,
                    status=err.response.status_code,
                )
                time.sleep(SLEEP)
            else:
                context.log.exception("Failed to fetch data: %s" % url)
                return None


def crawl_item(context: Context, listing: Dict[str, Any]) -> None:
    links = listing.get("links", {})
    url = urljoin(API_URL, links.get("self"))
    data = http_get(context, url, cache_days=45)
    if data is None:
        return
    person = context.make("Person")
    _, officer_id = url.rsplit("/", 1)
    person.id = context.make_slug(officer_id)

    person.add("name", listing.get("title"))
    person.add("notes", listing.get("description"))
    person.add("topics", "corp.disqual")
    source_url = urljoin(WEB_URL, links.get("self"))
    person.add("sourceUrl", source_url)

    h.apply_name(
        person,
        first_name=data.pop("forename", None),
        last_name=data.pop("surname", None),
        middle_name=data.pop("other_forenames", None),
        lang="eng",
    )
    person.add("title", data.pop("title", None))

    nationality = data.pop("nationality", None)
    if nationality is not None:
        person.add("nationality", nationality.split(","))
    person.add("birthDate", data.pop("date_of_birth", None))

    address = listing.get("address", {})
    address = h.make_address(
        context,
        full=listing.get("address_snippet"),
        street=address.get("address_line_1"),
        street2=address.get("premises"),
        city=address.get("locality"),
        postal_code=address.get("postal_code"),
        region=address.get("region"),
        # country_code=person.first("nationality"),
    )
    h.apply_address(context, person, address)

    for disqual in data.pop("disqualifications", []):
        case_id = disqual.get("case_identifier")
        sanction = h.make_sanction(context, person, key=case_id)
        sanction.add("recordId", case_id)
        sanction.add("startDate", disqual.get("disqualified_from"))
        sanction.add("endDate", disqual.get("disqualified_until"))
        sanction.add("listingDate", disqual.get("undertaken_on"))
        for key, value in disqual.get("reason", {}).items():
            value = value.replace("-", " ")
            reason = f"{key}: {value}"
            sanction.add("reason", reason)
        sanction.add("country", "gb")
        context.emit(sanction)

        address = disqual.get("address", {})
        address = h.make_address(
            context,
            full=listing.get("address_snippet"),
            street=address.get("address_line_1"),
            street2=address.get("premises"),
            city=address.get("locality"),
            postal_code=address.get("postal_code"),
            region=address.get("region"),
            # country_code=person.first("nationality"),
        )

        for company_name in disqual.get("company_names", []):
            company = context.make("Company")
            company.id = context.make_slug("named", company_name)
            company.add("name", company_name)
            company.add("jurisdiction", "gb")
            # company.add("topics", "crime")
            context.emit(company)
            h.apply_address(context, company, address)

            directorship = context.make("Directorship")
            directorship.id = context.make_id(person.id, company.id)
            directorship.add("director", person)
            directorship.add("organization", company)
            context.emit(directorship)

    context.emit(person, target=True)


def crawl(context: Context) -> None:
    if not len(API_KEY):
        context.log.error("Please set $OPENSANCTIONS_COH_API_KEY.")
        return
    try:
        for letter in string.ascii_uppercase:
            start_index = 0
            while True:
                params = {
                    "q": letter,
                    "start_index": str(start_index),
                    "items_per_page": "100",
                }
                data = http_get(context, SEARCH_URL, params=params, cache_days=5)
                if data is None:
                    break
                context.log.info("Search: %s" % letter, start_index=start_index)
                for item in data.pop("items", []):
                    crawl_item(context, item)
                start_index = data["start_index"] + data["items_per_page"]
                if data["total_results"] < start_index:
                    break
    except AbortCrawl:
        context.log.info("Rate limit exceeded, aborting.")
