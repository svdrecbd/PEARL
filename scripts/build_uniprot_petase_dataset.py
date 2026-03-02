from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from petase_family import compute_relevance_score


BASE_URL = "https://rest.uniprot.org/uniprotkb/search"
USER_AGENT = "codex-petase-dataset/1.0"
FIELDS = ",".join(
    [
        "accession",
        "id",
        "protein_name",
        "organism_name",
        "length",
        "ec",
        "annotation_score",
        "reviewed",
        "cc_function",
        "ft_act_site",
        "sequence",
    ]
)
AA_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
THERMO_PATTERN = re.compile(
    r"therm|geobacillus|saccharomonospora|thermobifida|thermomonospora|caldibacillus",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryProfile:
    queries: tuple[str, ...]
    min_relevance_score: int = 0


QUERY_PROFILES = {
    "petase_family_aggressive": QueryProfile(
        queries=(
            (
                '(protein_name:PETase OR protein_name:"PET hydrolase" OR '
                'protein_name:"poly(ethylene terephthalate) hydrolase" OR '
                'protein_name:"polyester hydrolase" OR protein_name:cutinase OR '
                "ec:3.1.1.74 OR ec:3.1.1.101)"
            ),
        ),
    ),
    "petase_family_reviewed": QueryProfile(
        queries=(
            (
                '(protein_name:PETase OR protein_name:"PET hydrolase" OR '
                'protein_name:"poly(ethylene terephthalate) hydrolase" OR '
                'protein_name:"polyester hydrolase" OR protein_name:cutinase OR '
                "ec:3.1.1.74 OR ec:3.1.1.101) AND reviewed:true"
            ),
        ),
    ),
    "polyester_hydrolase_expanded": QueryProfile(
        queries=(
            (
                '(protein_name:PETase OR protein_name:"PET hydrolase" OR '
                'protein_name:"poly(ethylene terephthalate) hydrolase" OR '
                'protein_name:"polyester hydrolase" OR protein_name:cutinase OR '
                "ec:3.1.1.74 OR ec:3.1.1.101)"
            ),
            (
                '(protein_name:polyesterase OR protein_name:"cutinase-like" OR '
                'protein_name:suberinase OR protein_name:"leaf-branch compost cutinase" OR '
                'protein_name:"polycaprolactone hydrolase" OR '
                'protein_name:"poly(lactic acid) depolymerase" OR protein_name:MHETase)'
            ),
            "cc_function:cutin",
            "cc_function:suberin",
        ),
        min_relevance_score=4,
    ),
}


@dataclass
class DatasetPaths:
    raw_jsonl: Path
    records_jsonl: Path
    train_prompts_jsonl: Path
    val_prompts_jsonl: Path
    test_prompts_jsonl: Path
    sequences_fasta: Path
    summary_json: Path


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = DatasetPaths(
        raw_jsonl=output_dir / "uniprot_petase_raw.jsonl",
        records_jsonl=output_dir / "petase_records.jsonl",
        train_prompts_jsonl=output_dir / "train_prompts.jsonl",
        val_prompts_jsonl=output_dir / "val_prompts.jsonl",
        test_prompts_jsonl=output_dir / "test_prompts.jsonl",
        sequences_fasta=output_dir / "petase_sequences.fasta",
        summary_json=output_dir / "dataset_summary.json",
    )

    profile = QUERY_PROFILES[args.profile]
    queries = profile.queries
    raw_records = fetch_records(
        queries=queries,
        page_size=args.page_size,
        max_records=args.max_records,
    )
    write_jsonl(paths.raw_jsonl, raw_records)

    min_relevance_score = profile.min_relevance_score if args.min_relevance_score is None else args.min_relevance_score
    normalized_records = normalize_records(
        raw_records,
        min_length=args.min_length,
        max_length=args.max_length,
        min_relevance_score=min_relevance_score,
    )
    write_jsonl(paths.records_jsonl, normalized_records)
    write_fasta(paths.sequences_fasta, normalized_records)

    prompt_rows = build_prompt_rows(normalized_records, prompts_per_record=args.prompts_per_record)
    split_rows = split_prompt_rows(prompt_rows, seed=args.seed)
    for path, rows in [
        (paths.train_prompts_jsonl, split_rows["train"]),
        (paths.val_prompts_jsonl, split_rows["val"]),
        (paths.test_prompts_jsonl, split_rows["test"]),
    ]:
        write_jsonl(path, rows)

    summary = {
        "profile": args.profile,
        "queries": list(queries),
        "raw_record_count": len(raw_records),
        "filtered_record_count": len(normalized_records),
        "prompt_count": len(prompt_rows),
        "split_counts": {name: len(rows) for name, rows in split_rows.items()},
        "min_length": args.min_length,
        "max_length": args.max_length,
        "min_relevance_score": min_relevance_score,
        "prompts_per_record": args.prompts_per_record,
        "seed": args.seed,
        "paths": {name: str(value) for name, value in paths.__dict__.items()},
    }
    paths.summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a UniProt PETase-family dataset")
    parser.add_argument("--output-dir", default="data/petase_family")
    parser.add_argument("--profile", choices=sorted(QUERY_PROFILES), default="petase_family_aggressive")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--min-length", type=int, default=120)
    parser.add_argument("--max-length", type=int, default=420)
    parser.add_argument("--min-relevance-score", type=int, default=None)
    parser.add_argument("--prompts-per-record", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


def fetch_records(*, queries: tuple[str, ...], page_size: int, max_records: int | None) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for query in queries:
        for record in fetch_records_for_query(query=query, page_size=page_size):
            accession = record.get("primaryAccession")
            if accession:
                merged[accession] = record
            if max_records is not None and len(merged) >= max_records:
                return list(merged.values())[:max_records]
    return list(merged.values())


def fetch_records_for_query(*, query: str, page_size: int) -> list[dict[str, Any]]:
    params = {
        "query": query,
        "format": "json",
        "size": page_size,
        "fields": FIELDS,
    }
    next_url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    results: list[dict[str, Any]] = []

    while next_url:
        request = urllib.request.Request(next_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
            batch = payload.get("results", [])
            results.extend(batch)
            next_url = parse_next_link(response.headers.get("Link"))

    return results


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
    if match:
        return match.group(1)
    return None


def normalize_records(
    raw_records: list[dict[str, Any]],
    *,
    min_length: int,
    max_length: int,
    min_relevance_score: int,
) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for raw in raw_records:
        normalized = normalize_record(raw)
        if normalized is None:
            continue
        if not (min_length <= normalized["length"] <= max_length):
            continue
        sequence = normalized["sequence"]
        if not AA_PATTERN.fullmatch(sequence):
            continue
        relevance_score, matched_terms = compute_relevance_score(normalized)
        if relevance_score < min_relevance_score:
            continue
        normalized["relevance_score"] = relevance_score
        normalized["matched_relevance_terms"] = matched_terms
        key = hashlib.sha256(sequence.encode("utf-8")).hexdigest()
        if key in deduped:
            deduped[key]["source_accessions"].append(normalized["accession"])
            continue
        normalized["sequence_sha256"] = key
        normalized["source_accessions"] = [normalized["accession"]]
        deduped[key] = normalized
    return list(deduped.values())


def normalize_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    sequence = raw.get("sequence", {}).get("value")
    if not isinstance(sequence, str) or not sequence:
        return None

    protein_name, alternative_names, ec_numbers = extract_names_and_ec(raw.get("proteinDescription", {}))
    function_texts = extract_function_texts(raw.get("comments", []))
    active_sites = extract_active_sites(raw.get("features", []))
    organism = raw.get("organism", {})
    organism_name = organism.get("scientificName")
    lineage = organism.get("lineage", [])

    return {
        "accession": raw.get("primaryAccession"),
        "uniprot_id": raw.get("uniProtkbId"),
        "reviewed": "reviewed" in str(raw.get("entryType", "")).lower(),
        "annotation_score": raw.get("annotationScore"),
        "protein_name": protein_name,
        "alternative_names": alternative_names,
        "ec_numbers": sorted(ec_numbers),
        "organism_name": organism_name,
        "taxon_id": organism.get("taxonId"),
        "lineage": lineage,
        "is_thermophile_hint": bool(organism_name and THERMO_PATTERN.search(organism_name)),
        "length": int(raw.get("sequence", {}).get("length", len(sequence))),
        "sequence": sequence,
        "function_texts": function_texts,
        "active_sites": active_sites,
    }


def extract_names_and_ec(protein_description: dict[str, Any]) -> tuple[str | None, list[str], set[str]]:
    recommended = protein_description.get("recommendedName", {})
    recommended_name = recommended.get("fullName", {}).get("value")
    ec_numbers = {entry.get("value") for entry in recommended.get("ecNumbers", []) if entry.get("value")}
    alternative_names: list[str] = []

    for alt in protein_description.get("alternativeNames", []):
        full_name = alt.get("fullName", {}).get("value")
        if full_name:
            alternative_names.append(full_name)
        for short_name in alt.get("shortNames", []):
            value = short_name.get("value")
            if value:
                alternative_names.append(value)
        for ec_number in alt.get("ecNumbers", []):
            value = ec_number.get("value")
            if value:
                ec_numbers.add(value)

    return recommended_name, sorted(set(alternative_names)), ec_numbers


def extract_function_texts(comments: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for comment in comments:
        for text in comment.get("texts", []):
            value = text.get("value")
            if value:
                texts.append(clean_comment_text(value))
    return texts


def clean_comment_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\(PubMed:[^)]+\)", "", value)).strip()


def extract_active_sites(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active_sites: list[dict[str, Any]] = []
    for feature in features:
        if feature.get("type") != "Active site":
            continue
        location = feature.get("location", {})
        start = location.get("start", {}).get("value")
        end = location.get("end", {}).get("value")
        active_sites.append(
            {
                "description": feature.get("description"),
                "start": start,
                "end": end,
            }
        )
    return active_sites


def build_prompt_rows(records: list[dict[str, Any]], *, prompts_per_record: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        prompts = generate_prompts(record)[:prompts_per_record]
        for idx, prompt in enumerate(prompts):
            rows.append(
                {
                    "prompt_id": f"{record['accession']}:{idx}",
                    "accession": record["accession"],
                    "prompt": prompt,
                    "protein_name": record["protein_name"],
                    "organism_name": record["organism_name"],
                    "length": record["length"],
                    "ec_numbers": record["ec_numbers"],
                    "is_thermophile_hint": record["is_thermophile_hint"],
                    "relevance_score": record.get("relevance_score", 0),
                    "sequence_sha256": record["sequence_sha256"],
                }
            )
    return rows


def generate_prompts(record: dict[str, Any]) -> list[str]:
    protein_name = record.get("protein_name") or "PETase-family hydrolase"
    organism_name = record.get("organism_name") or "a microbial source"
    ec_hint = f" EC {record['ec_numbers'][0]}." if record.get("ec_numbers") else ""
    function_hint = ""
    if record.get("function_texts"):
        function_hint = f" Function hint: {record['function_texts'][0][:200]}."

    family_hint = "thermophilic" if record.get("is_thermophile_hint") else "polyester-hydrolase-family"
    length_hint = record["length"]
    motif_hint = " Favor a PETase/cutinase-like GxSxG nucleophile motif and compatible catalytic residues."
    return [
        (
            f"Generate a {family_hint} {protein_name} sequence around {length_hint} amino acids long."
            f"{motif_hint}"
            " Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
        ),
        (
            f"Design a protein sequence inspired by {protein_name} from {organism_name}, length about {length_hint} aa."
            f"{ec_hint}{function_hint}{motif_hint} Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
        ),
        (
            f"Generate a novel polyester hydrolase sequence with length near {length_hint} aa and plausible PETase/cutinase-like catalytic residues."
            " Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
        ),
    ]


def split_prompt_rows(rows: list[dict[str, Any]], *, seed: int) -> dict[str, list[dict[str, Any]]]:
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    total = len(shuffled)
    train_end = int(total * 0.9)
    val_end = int(total * 0.95)
    return {
        "train": shuffled[:train_end],
        "val": shuffled[train_end:val_end],
        "test": shuffled[val_end:],
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def write_fasta(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            header = f">{row['accession']} {row.get('protein_name') or 'PETase-family'}"
            handle.write(header)
            handle.write("\n")
            sequence = row["sequence"]
            for start in range(0, len(sequence), 80):
                handle.write(sequence[start : start + 80])
                handle.write("\n")


if __name__ == "__main__":
    main()
