import json
import sys
from pathlib import Path


def main():
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

    from src.schemas import EventDocument

    output_path = project_root / "artifacts" / "m05-schema.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            EventDocument.model_json_schema(),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Esquema exportado a {output_path}")


if __name__ == "__main__":
    main()