"""Check local Markdown links without requiring a network or Markdown server."""

import re
from pathlib import Path
from urllib.parse import unquote


def main():
    sources = [
        Path(name)
        for name in ("README.md", "ARCHITECTURE.md", "THREAT_MODEL.md", "CONTRIBUTING.md")
    ]
    sources.extend(Path("docs").glob("*.md"))
    failures = []
    checked = 0
    for source in sources:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", source.read_text()):
            path = unquote(target.split("#")[0])
            if not path or path.startswith(("https:", "http:", "mailto:")):
                continue
            checked += 1
            if not (source.parent / path).exists():
                failures.append(f"{source}: {target}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"{checked} local documentation/media links verified.")


if __name__ == "__main__":
    main()
