from __future__ import annotations

import argparse
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from risk_agent_platform.config import Settings
from risk_agent_platform.model_profiles import ModelProfileRouter


SYSTEM_PROMPT = """You translate risk-analysis Markdown reports into Japanese.
Return only translated Markdown. Preserve all headings, bullets, tables, code spans, IDs, URLs,
file paths, metadata keys, JSON-like key names, scenario IDs, evidence IDs, and numeric values.
Do not summarize, omit, reorder, or add content. Do not explain the translation.
Do not output reasoning, checklists, source text, constraint text, self-corrections,
or labels such as "Original", "Translated", "Step", "Check", or "Let's"."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--chunk-chars", type=int, default=5000)
    parser.add_argument("--profile", default="long_context")
    parser.add_argument("--scenario-index", type=int, action="append", help="1-based scenario index to translate")
    parser.add_argument("--force", action="store_true", help="retranslate even when target is newer than source")
    args = parser.parse_args()

    root = args.project_root
    settings = Settings.load(root)
    router = ModelProfileRouter(root / "config" / "model_profiles.yaml")
    profile = router.select(args.profile)
    model = router.chat_model(settings, profile)

    scenario_indexes = args.scenario_index or list(range(1, 7))
    for idx in scenario_indexes:
        scenario_id = f"experiment_major_escalation_of_war_involving_ir_agg_{idx:03d}"
        source_path = root / "outputs" / scenario_id / "final_brief.md"
        target_path = root / "outputs" / scenario_id / "final_brief_ja.md"
        if not args.force and target_path.exists() and target_path.stat().st_mtime >= source_path.stat().st_mtime:
            print(f"skip_up_to_date={target_path}", flush=True)
            continue
        text = source_path.read_text(encoding="utf-8")
        chunks = _split_markdown(text, max_chars=args.chunk_chars)
        translated_chunks: list[str] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            started = time.perf_counter()
            print(f"translating={target_path} chunk={chunk_index}/{len(chunks)}", flush=True)
            response = model.invoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Translate only the Markdown between <markdown> and </markdown> to Japanese. "
                            f"Return only the translated Markdown, with no wrapper tags. "
                            f"Chunk {chunk_index} of {len(chunks)}.\n\n<markdown>\n{chunk}\n</markdown>"
                        )
                    ),
                ]
            )
            translated_chunks.append(str(response.content).strip())
            elapsed = time.perf_counter() - started
            print(f"translated_chunk={target_path} chunk={chunk_index}/{len(chunks)} seconds={elapsed:.1f}", flush=True)
        target_path.write_text("\n\n".join(translated_chunks).strip() + "\n", encoding="utf-8")
        print(f"translated={target_path}", flush=True)
    return 0


def _split_markdown(text: str, *, max_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        candidate_len = current_len + len(line) + 1
        if current and candidate_len > max_chars and _can_break_before(line):
            chunks.append("\n".join(current).strip())
            current = [line]
            current_len = len(line) + 1
            continue
        if current and candidate_len > max_chars * 1.35:
            chunks.append("\n".join(current).strip())
            current = [line]
            current_len = len(line) + 1
            continue
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current).strip())
    return chunks


def _can_break_before(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#") or stripped.startswith("- **") or stripped.startswith("## ")


if __name__ == "__main__":
    raise SystemExit(main())
