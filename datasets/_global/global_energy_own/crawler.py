from openpyxl import load_workbook
import openpyxl
from typing import Dict
from pantomime.types import XLSX

from zavod import Context
from zavod import helpers as h

IGNORE = [
    "sequence_no",
    "us_eia_860",
    "parent_entity_ids",
    "parents",
    "headquarters_country",
    "publicly_listed",
    "decision_date",
    "gcpt_announced_mw",
    "gcpt_cancelled_mw",
    "gcpt_construction_mw",
    "gcpt_mothballed_mw",
    "gcpt_operating_mw",
    "gcpt_permitted_mw",
    "gcpt_pre_permit_mw",
    "gcpt_retired_mw",
    "gcpt_shelved_mw",
    "gogpt_announced_mw",
    "gogpt_cancelled_mw",
    "gogpt_construction_mw",
    "gogpt_mothballed_mw",
    "gogpt_operating_mw",
    "gogpt_pre_construction_mw",
    "gogpt_retired_mw",
    "gogpt_shelved_mw",
    "gbpt_announced_mw",
    "gbpt_construction_mw",
    "gbpt_mothballed_mw",
    "gbpt_operating_mw",
    "gbpt_pre_construction_mw",
    "gbpt_retired_mw",
    "gbpt_shelved_mw",
    "gbpt_cancelled_mw",
    "gcmt_proposed_mtpa",
    "gcmt_operating_mtpa",
    "gcmt_shelved_mtpa",
    "gcmt_mothballed_mtpa",
    "gcmt_cancelled_mtpa",
    "gspt_operating_ttpa",
    "gspt_announced_ttpa",
    "gspt_construction_ttpa",
    "gspt_retired_ttpa",
    "gspt_operating_pre_retirement_ttpa",
    "gspt_mothballed_ttpa",
    "gspt_cancelled_ttpa",
    "total",
]


def crawl_row(context: Context, row: Dict[str, str]):
    id = row.pop("entity_id")
    name = row.pop("entity_name")
    original_name = row.pop("name_local", "")
    reg_country = row.pop("registration_country", "")
    entity_type = row.pop("entity_type", "")

    # legal entity
    # arrangement
    # state body
    # state
    # unknown entity
    # person
    if entity_type == "legal entity":
        schema = "Company"
    elif entity_type == "state body" or entity_type == "state":
        schema = "PublicBody"
    elif entity_type == "person":
        schema = "Person"
    else:
        schema = "Company"

    entity = context.make(schema)
    entity.id = context.make_id(name, id, reg_country, entity_type)
    entity.add("name", name)
    entity.add("name", original_name)
    entity.add("alias", row.pop("name_other", ""))
    entity.add("weakAlias", row.pop("abbreviation", ""))
    entity.add("idNumber", row.pop("legal_entity_identifier", ""))
    entity.add("description", entity_type)
    entity.add("country", reg_country)
    entity.add("website", row.pop("home_page", ""))
    if schema != "PublicBody" and schema != "Person":
        entity.add("permId", row.pop("refinitiv_permid", ""))
        entity.add("cikCode", row.pop("sec_central_index_key", ""))
    address = h.make_address(
        context,
        country=reg_country,
        state=row.pop("registration_subdivision", ""),
        city=row.pop("headquarters_subdivision", ""),
    )
    h.copy_address(entity, address)

    context.emit(entity)
    context.audit_data(
        row,
        ignore=IGNORE,
    )


def crawl(context: Context):
    path = context.fetch_resource("source.xlsx", context.data_url)
    context.export_resource(path, XLSX, title=context.SOURCE_TITLE)

    workbook: openpyxl.Workbook = openpyxl.load_workbook(path, read_only=True)
    sheet = workbook["Immediate Owner Entities"]

    for row in h.parse_xlsx_sheet(context, sheet=sheet):
        crawl_row(context, row)
