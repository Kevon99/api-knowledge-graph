"""Test de correlacion: agrupacion por sesion y materializacion en el grafo."""

from pathlib import Path

from akg.pipeline.correlator import correlate_exchanges, group_by_session, session_key_of
from akg.pipeline.importers import get_adapter
from akg.pipeline.normalizer import normalize

SAMPLE = Path("dev/samples/burp_sample.json")


def main() -> None:
    adapter = get_adapter("burp_json")
    with SAMPLE.open("rb") as fh:
        exchanges, errors = adapter.parse(fh)

    norm = [normalize(e) for e in exchanges]
    print("normalized:", len(norm))

    for e in norm:
        print(f"  {e.method} {e.template!r:<40} session={session_key_of(e)[:24]}")

    buckets = group_by_session(norm)
    print("session buckets:", {k[:20]: len(v) for k, v in buckets.items()})

    import uuid

    counts = correlate_exchanges(
        norm,
        project="sprint-demo",
        import_id=uuid.UUID("019fc9bb-19ba-7e7c-213a-4fc6d20f1c01"),
    )
    print("correlation:", counts)


if __name__ == "__main__":
    main()