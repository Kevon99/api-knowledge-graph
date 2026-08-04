from akg.pipeline.importers.base import ImportAdapter, ValidationReport
from akg.pipeline.importers.burp import BurpJsonAdapter
from akg.pipeline.importers.burp_csv import BurpCsvAdapter
from akg.pipeline.importers.burp_xml import BurpXmlAdapter

ADAPTER_BY_FORMAT: dict[str, ImportAdapter] = {
    "burp_json": BurpJsonAdapter(),
    "burp_csv": BurpCsvAdapter(),
    "burp_xml": BurpXmlAdapter(),
}


def get_adapter(format_name: str) -> ImportAdapter:
    try:
        return ADAPTER_BY_FORMAT[format_name]
    except KeyError:
        raise ValueError(f"formato de importacion no soportado: {format_name!r}") from None


__all__ = ["ImportAdapter", "ValidationReport", "BurpJsonAdapter", "BurpCsvAdapter", "BurpXmlAdapter", "get_adapter"]
