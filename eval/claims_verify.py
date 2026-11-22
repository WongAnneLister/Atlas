"""Run the runtime claim checks over the frozen claim set and save one verdict per claim.

Each claim goes through the same two steps as `graph/nodes/ground.py`: the literal check in
code, then the verifier model with the claim's question as context and only its cited text
as evidence. Claims are verified one per call (runtime batches the claims of one answer);
a verifier call that fails or returns invalid output counts as `unsupported`, because the
runtime then withholds the answer. The output is the prediction file `make eval-claims`
scores, so labels can change later without new model calls.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from eval.build_claims import CLAIMS_PATH, NAME, read_claims
from eval.claims_eval import Prediction, PredictionRun
from eval.e2e_eval import _model_names
from eval.registry import file_hash, load_registry
from eval.run_record import RUNS, git
from eval.schema import ClaimItem, ClaimVerdict
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.graph.deps import GraphDeps
from support_agent.grounding.claims import Claim, ClaimEvidence
from support_agent.grounding.exact import missing_literals
from support_agent.grounding.verify import verify_claims
from support_agent.llm import Role
from support_agent.reliability.llm_calls import ReliableModels

OUTPUT = RUNS / "claims-verify"


def verdict_for(models: ReliableModels, role: Role, item: ClaimItem) -> tuple[ClaimVerdict, str]:
    """Return (verdict, reason) for one claim, as the runtime would judge it."""
    evidence = [ClaimEvidence(n=source.n, text=source.text) for source in item.sources]
    if not evidence:
        return "unsupported", "missing_citation"
    if missing := missing_literals(item.claim, [source.text for source in evidence]):
        return "unsupported", "missing_literal: " + ", ".join(missing)
    claim = Claim(number=1, part=0, text=item.claim, question=item.question, sources=evidence)
    try:
        assessment = verify_claims(models, role, [claim])[1]
    except Exception as error:  # the runtime fails closed on any verifier error
        return "unsupported", f"verifier_error: {type(error).__name__}"
    return assessment.verdict, assessment.reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    load_dotenv(REPO_ROOT / ".env", override=False)
    get_settings.cache_clear()
    settings = get_settings()
    entry = load_registry()[NAME]
    if file_hash(CLAIMS_PATH) != entry.sha256:
        parser.error("Local claim set differs from the registry")
    items = [item for item in read_claims() if item.split == args.split]
    sha = git("rev-parse", "HEAD")
    role = settings.grounding.verifier_role
    with GraphDeps(settings) as deps, ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda item: verdict_for(deps.models, role, item), items))
    run = PredictionRun(
        git_sha=sha,
        config_hash=digest(
            json_text(
                {
                    "grounding": settings.grounding.model_dump(mode="json"),
                    "llm": settings.llm.model_dump(mode="json"),
                }
            )
        ),
        dataset_sha256=entry.sha256,
        models=_model_names(settings),
        date=datetime.now(UTC).isoformat(),
        split=args.split,
        predictions=[
            Prediction(id=item.id, verdict=verdict)
            for item, (verdict, _) in zip(items, results, strict=True)
        ],
    )
    output = args.output or OUTPUT / f"{args.split}-{entry.version}-{sha[:8]}.json"
    write_text(output, run.model_dump_json(indent=2) + "\n")
    reasons_file = output.with_suffix(".reasons.json")
    write_text(
        reasons_file,
        json_text({item.id: reason for item, (_, reason) in zip(items, results, strict=True)}),
    )
    reasons = Counter(reason.split(":")[0] for _, reason in results)
    sys.stdout.write(f"{output}\n{dict(sorted(reasons.items()))}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
