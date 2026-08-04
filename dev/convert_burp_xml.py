"""Convierte un export XML estandar de Burp Suite a JSON del proyecto.

Uso:
    uv run python dev/convert_burp_xml.py <entrada.xml> <salida.json>

El JSON de salida sigue el formato esperado por el pipeline
(ver dev/samples/burp_sample.json):

    [
      {
        "host": "admin.example.com",
        "method": "GET",
        "url": "https://admin.example.com/api/config",
        "time": 1730000002200,
        "request": "GET /api/config HTTP/1.1\\r\\nHost: ...\\r\\n\\r\\n",
        "response": "HTTP/1.1 200 OK\\r\\n...\\r\\n\\r\\n{...}"
      },
      ...
    ]

Cada item con error de parseo se reporta en stderr pero no aborta la
conversion. Al final se imprime un resumen con el conteo.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Agregar la raiz del proyecto al path para poder importar `akg` cuando el
# script se ejecuta directamente sin instalar el paquete.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from akg.pipeline.httpparser import parse_raw_request
from akg.pipeline.importers.burp_xml import _maybe_b64decode, _parse_timestamp


def _read_item(elem: ET.Element) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for child in elem:
        text = child.text or ""
        if child.get("base64") == "true":
            text = _maybe_b64decode(text)
        item[child.tag] = text
    return item


def _url_time_to_ms(ts: datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return int(ts.timestamp() * 1000)


def _to_entry(order: int, item: dict[str, Any]) -> dict[str, Any]:
    url = item.get("url") or ""
    method = item.get("method") or "GET"
    ts = _parse_timestamp(item.get("time"))
    url_parts = urllib.parse.urlsplit(url)

    req_text = item.get("request")
    resp_text = item.get("response")

    if req_text:
        try:
            parsed_req = parse_raw_request(req_text)
            host = parsed_req["host"] or item.get("host") or (url_parts.hostname or "")
        except Exception:
            host = item.get("host") or (url_parts.hostname or "")
    else:
        host = item.get("host") or (url_parts.hostname or "")

    return {
        "host": host,
        "method": method,
        "url": url,
        "time": _url_time_to_ms(ts),
        "request": req_text or "",
        "response": resp_text or "",
    }


def convert(input_path: str, output_path: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    total = 0
    written = 0

    with Path(input_path).open("rb") as fh:
        context = ET.iterparse(fh, events=("end",))
        with Path(output_path).open("w", encoding="utf-8") as out:
            out.write("[\n")
            first = True
            order = 0
            for _, elem in context:
                if elem.tag != "item":
                    continue
                total += 1
                try:
                    entry = _to_entry(order, _read_item(elem))
                except Exception as exc:
                    errors.append({"line": order, "error": str(exc)})
                    order += 1
                    elem.clear()
                    continue
                if not first:
                    out.write(",\n")
                json.dump(entry, out, ensure_ascii=False)
                first = False
                written += 1
                order += 1
                elem.clear()
            out.write("\n]\n")

    return {"total_items": total, "written": written, "errors": len(errors), "error_details": errors[:10]}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convierte un export XML de Burp Suite a JSON del proyecto."
    )
    parser.add_argument("input", help="archivo XML de Burp Suite (con request/response en base64)")
    parser.add_argument("output", help="archivo JSON de salida en el formato del proyecto")
    parser.add_argument("--stats", action="store_true", help="imprime resumen de la conversion")
    args = parser.parse_args()

    stats = convert(args.input, args.output)

    if stats["errors"]:
        print(f"items totales: {stats['total_items']}", file=sys.stderr)
        print(f"convertidos:   {stats['written']}", file=sys.stderr)
        print(f"errores:       {stats['errors']}", file=sys.stderr)
        for err in stats["error_details"]:
            print(f"  line {err['line']}: {err['error']}", file=sys.stderr)
    else:
        print(f"convertidos: {stats['written']} items -> {args.output}", file=sys.stderr)

    if args.stats:
        print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
