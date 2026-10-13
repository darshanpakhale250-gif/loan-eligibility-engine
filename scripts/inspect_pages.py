
import json
from pathlib import Path

pages_file = Path("data/pages.jsonl")

keywords = [
    "eligibility",
    "age",
    "interest rate",
    "processing fee",
    "processing charges",
    "loan amount",
    "documents required",
    "monthly income",
    "repayment",
    "tenure",
]

with pages_file.open("r", encoding="utf-8") as file:
    pages = [
        json.loads(line)
        for line in file
        if line.strip()
    ]

for page in pages:
    text = page.get("markdown", "")
    lower_text = text.lower()

    print("\n" + "=" * 70)
    print("TITLE:", page.get("title"))
    print("URL:", page.get("url"))
    print("=" * 70)

    shown_positions = set()

    for keyword in keywords:
        start = 0
        matches = 0

        while matches < 3:
            pos = lower_text.find(keyword, start)

            if pos == -1:
                break

            # Avoid printing nearly identical snippets.
            if not any(abs(pos - old) < 150 for old in shown_positions):
                snippet = text[max(0, pos - 250):pos + 500]
                print(f"\n[{keyword}]\n{snippet}\n")
                shown_positions.add(pos)

            matches += 1
            start = pos + len(keyword)
