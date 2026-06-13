"""Automated local structure gate: fold a candidate, then check fold quality and the
*real* 3D catalytic-triad geometry — the side-chain hydrogen-bond network, not 1D sequence
spacing and not coarse CA distances.

This is the truth-grounded gate that sits between the cheap sequence screens and the
expensive/manual ColabFold step. Folding backends are pluggable:

- ``esmatlas``: POST to the ESMAtlas ESMFold API (no local weights; matches the existing
  ``scripts/fold_phase7_subset.py`` pattern). Best for low-volume gating.
- ``esmfold``: local ``transformers`` ``EsmForProteinFolding`` (offline, reproducible,
  needs the ~2.8 GB ``facebook/esmfold_v1`` weights).

An ESM3 backend can be added behind the same ``FoldingBackend`` protocol once the
``esm`` package and (non-commercial) open weights are installed.

The catalytic triad of a serine hydrolase is a Ser-His-Asp hydrogen-bond relay:
Ser(OG)···His(NE2/ND1) and His(ND1/NE2)···Asp(OD1/OD2), each a ~2.6-3.3 A H-bond. We pick
the nucleophile serines from GxSxG motifs, then select the His/Asp partners by genuine 3D
proximity and score the two H-bond distances. Coarse CA distances are kept only as a
fallback when side-chain atoms are unavailable.
"""
from __future__ import annotations

import bisect
import json
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from pearl.family import SERINE_MOTIF_PATTERN

_CONFIGS_DIR = Path(
    os.environ.get("STRUCTURE_GATE_CALIBRATION_DIR", str(Path(__file__).resolve().parents[2] / "configs"))
)

# pLDDT gate matches the existing scripts/fold_phase7_subset.py convention.
STRUCTURE_PLDDT_GATE = float(os.environ.get("STRUCTURE_PLDDT_GATE", "70.0"))
# Catalytic H-bond donor/acceptor heavy-atom distance ceiling (Angstrom). A real triad
# H-bond is ~2.6-3.3 A; 3.5 A allows for fold/rotamer noise without admitting non-contacts.
TRIAD_HBOND_MAX_ANGSTROM = float(os.environ.get("TRIAD_HBOND_MAX_ANGSTROM", "3.5"))
# CA-distance fallback window (used only when side-chain atoms are missing), matching the
# loose limits the legacy parse_colabfold_outputs.py used.
CA_FALLBACK_MIN_ANGSTROM = 4.0
CA_FALLBACK_MAX_ANGSTROM = 20.0

SERINE_HYDROXYL_ATOM = "OG"
HISTIDINE_IMIDAZOLE_NITROGENS = ("ND1", "NE2")
ASPARTATE_CARBOXYL_OXYGENS = ("OD1", "OD2")

Coord = tuple[float, float, float]


@dataclass
class Residue:
    resseq: int
    resname: str
    atoms: dict[str, Coord] = field(default_factory=dict)
    ca_plddt: float | None = None


@dataclass
class StructurePrediction:
    sequence: str
    residues: dict[int, Residue]
    mean_plddt: float
    backend: str
    pdb_text: str = ""


class FoldingBackend(Protocol):
    name: str

    def fold(self, sequence: str) -> str:
        """Return a PDB text string for the given amino-acid sequence."""


def distance(a: Coord, b: Coord) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def parse_pdb(pdb_text: str) -> tuple[dict[int, Residue], float]:
    """Parse ATOM records into per-residue atom coordinates and read pLDDT from B-factors.

    ESMFold/ESMAtlas/ColabFold all write the per-residue pLDDT into the B-factor column.
    """
    residues: dict[int, Residue] = {}
    plddts: list[float] = []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        try:
            atom_name = line[12:16].strip()
            resname = line[17:20].strip()
            resseq = int(line[22:26])
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            b_factor = float(line[60:66])
        except (ValueError, IndexError):
            continue
        residue = residues.get(resseq)
        if residue is None:
            residue = Residue(resseq=resseq, resname=resname)
            residues[resseq] = residue
        residue.atoms[atom_name] = (x, y, z)
        if atom_name == "CA":
            residue.ca_plddt = b_factor
            plddts.append(b_factor)

    mean_plddt = sum(plddts) / len(plddts) if plddts else 0.0
    if 0.0 < mean_plddt <= 1.0:
        mean_plddt *= 100.0  # normalize 0-1 pLDDT to the 0-100 convention
    return residues, mean_plddt


def serine_nucleophile_positions(sequence: str) -> list[int]:
    """1-based residue positions of the serine in each GxSxG motif (the nucleophile candidate)."""
    positions: list[int] = []
    for index in range(len(sequence) - 4):
        if SERINE_MOTIF_PATTERN.fullmatch(sequence[index : index + 5]):
            positions.append(index + 3)  # G x S x G -> S is the 3rd residue (1-based offset +3)
    return positions


def _residues_by_name(residues: dict[int, Residue], resname: str) -> list[Residue]:
    return [residue for residue in residues.values() if residue.resname == resname]


def _min_atom_distance(
    source: Coord,
    residue: Residue,
    atom_names: tuple[str, ...],
) -> float | None:
    candidates = [residue.atoms[name] for name in atom_names if name in residue.atoms]
    if not candidates:
        return None
    return min(distance(source, atom) for atom in candidates)


@dataclass
class TriadResult:
    found: bool
    method: str  # "sidechain", "ca_fallback", or "none"
    ser_resseq: int | None = None
    his_resseq: int | None = None
    asp_resseq: int | None = None
    ser_his_distance: float | None = None  # Ser OG ... His imidazole N
    his_asp_distance: float | None = None  # His imidazole N ... Asp carboxyl O
    passes: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "found": self.found,
            "method": self.method,
            "ser_resseq": self.ser_resseq,
            "his_resseq": self.his_resseq,
            "asp_resseq": self.asp_resseq,
            "ser_his_distance": round(self.ser_his_distance, 3) if self.ser_his_distance is not None else None,
            "his_asp_distance": round(self.his_asp_distance, 3) if self.his_asp_distance is not None else None,
            "passes": self.passes,
        }


def find_catalytic_triad(
    sequence: str,
    residues: dict[int, Residue],
    *,
    hbond_max: float = TRIAD_HBOND_MAX_ANGSTROM,
) -> TriadResult:
    """Select the best Ser-His-Asp triad by real 3D proximity and score its two H-bonds.

    Nucleophile serines come from GxSxG motifs; the His and Asp partners are chosen by
    minimizing the catalytic H-bond distances, not by 1D sequence order.
    """
    ser_positions = serine_nucleophile_positions(sequence)
    histidines = _residues_by_name(residues, "HIS")
    aspartates = _residues_by_name(residues, "ASP")

    best: TriadResult | None = None
    best_score = math.inf
    sidechain_data_present = False

    for ser_pos in ser_positions:
        ser_residue = residues.get(ser_pos)
        if ser_residue is None:
            continue
        ser_og = ser_residue.atoms.get(SERINE_HYDROXYL_ATOM)
        if ser_og is None or not histidines or not aspartates:
            continue
        for his in histidines:
            ser_his = _min_atom_distance(ser_og, his, HISTIDINE_IMIDAZOLE_NITROGENS)
            if ser_his is None:
                continue
            his_nitrogens = [his.atoms[name] for name in HISTIDINE_IMIDAZOLE_NITROGENS if name in his.atoms]
            for asp in aspartates:
                his_asp: float | None = None
                for nitrogen in his_nitrogens:
                    candidate = _min_atom_distance(nitrogen, asp, ASPARTATE_CARBOXYL_OXYGENS)
                    if candidate is not None and (his_asp is None or candidate < his_asp):
                        his_asp = candidate
                if his_asp is None:
                    continue
                sidechain_data_present = True
                score = ser_his + his_asp
                if score < best_score:
                    best_score = score
                    best = TriadResult(
                        found=True,
                        method="sidechain",
                        ser_resseq=ser_pos,
                        his_resseq=his.resseq,
                        asp_resseq=asp.resseq,
                        ser_his_distance=ser_his,
                        his_asp_distance=his_asp,
                        passes=(ser_his <= hbond_max and his_asp <= hbond_max),
                    )

    if best is not None:
        return best
    if sidechain_data_present:
        return TriadResult(found=False, method="sidechain")
    return _ca_fallback_triad(sequence, residues, ser_positions, histidines, aspartates)


def _ca_fallback_triad(
    sequence: str,
    residues: dict[int, Residue],
    ser_positions: list[int],
    histidines: list[Residue],
    aspartates: list[Residue],
) -> TriadResult:
    """Coarse CA-only triad check used only when side-chain atoms are absent from the model."""
    for ser_pos in ser_positions:
        ser_residue = residues.get(ser_pos)
        ser_ca = ser_residue.atoms.get("CA") if ser_residue else None
        if ser_ca is None or not histidines or not aspartates:
            continue
        best: TriadResult | None = None
        best_score = math.inf
        for his in histidines:
            his_ca = his.atoms.get("CA")
            if his_ca is None:
                continue
            ser_his = distance(ser_ca, his_ca)
            for asp in aspartates:
                asp_ca = asp.atoms.get("CA")
                if asp_ca is None:
                    continue
                his_asp = distance(his_ca, asp_ca)
                score = ser_his + his_asp
                if score < best_score:
                    best_score = score
                    passes = (
                        CA_FALLBACK_MIN_ANGSTROM <= ser_his <= CA_FALLBACK_MAX_ANGSTROM
                        and CA_FALLBACK_MIN_ANGSTROM <= his_asp <= CA_FALLBACK_MAX_ANGSTROM
                    )
                    best = TriadResult(
                        found=True,
                        method="ca_fallback",
                        ser_resseq=ser_pos,
                        his_resseq=his.resseq,
                        asp_resseq=asp.resseq,
                        ser_his_distance=ser_his,
                        his_asp_distance=his_asp,
                        passes=passes,
                    )
        if best is not None:
            return best
    return TriadResult(found=False, method="none")


def _calibration_key(backend_name: str) -> str:
    # esmfold and esmatlas are the same ESMFold model -> shared structural distribution.
    return "esm3" if backend_name == "esm3" else "esmfold"


def _structure_calibration_path(backend_name: str) -> Path:
    explicit = os.environ.get("STRUCTURE_GATE_CALIBRATION_PATH", "").strip()
    if explicit:
        return Path(explicit)
    return _CONFIGS_DIR / f"structure_gate_calibration.{_calibration_key(backend_name)}.json"


@lru_cache(maxsize=8)
def load_structure_calibration(backend_name: str) -> dict | None:
    """Load the natural-reference structural distribution for a folder family, or None."""
    path = _structure_calibration_path(backend_name)
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    plddt = sorted(float(v) for v in payload.get("plddt", []))
    if not plddt:
        return None
    return {
        "backend": payload.get("backend"),
        "count": int(payload.get("count", len(plddt))),
        "plddt": plddt,
        "ser_his": sorted(float(v) for v in payload.get("ser_his", [])),
        "his_asp": sorted(float(v) for v in payload.get("his_asp", [])),
    }


def _fraction_at_or_below(sorted_values: list[float], value: float) -> float:
    if not sorted_values:
        return 0.0
    return bisect.bisect_right(sorted_values, value) / len(sorted_values)


def _fraction_at_or_above(sorted_values: list[float], value: float) -> float:
    if not sorted_values:
        return 0.0
    return (len(sorted_values) - bisect.bisect_left(sorted_values, value)) / len(sorted_values)


def structural_grade(
    *,
    mean_plddt: float,
    ser_his_distance: float | None,
    his_asp_distance: float | None,
    calibration: dict,
) -> dict[str, object]:
    """Graded [0,1] structural score vs natural folds: high pLDDT and tight triad H-bonds score high."""
    plddt_percentile = _fraction_at_or_below(calibration["plddt"], mean_plddt)
    components = [plddt_percentile]
    ser_his_percentile = his_asp_percentile = None
    if ser_his_distance is not None and calibration["ser_his"]:
        ser_his_percentile = _fraction_at_or_above(calibration["ser_his"], ser_his_distance)
        components.append(ser_his_percentile)
    if his_asp_distance is not None and calibration["his_asp"]:
        his_asp_percentile = _fraction_at_or_above(calibration["his_asp"], his_asp_distance)
        components.append(his_asp_percentile)
    return {
        "plddt_natural_percentile": round(plddt_percentile, 4),
        "ser_his_tightness_percentile": round(ser_his_percentile, 4) if ser_his_percentile is not None else None,
        "his_asp_tightness_percentile": round(his_asp_percentile, 4) if his_asp_percentile is not None else None,
        "structural_score": round(sum(components) / len(components), 4),
    }


def gate_prediction(
    prediction: StructurePrediction,
    *,
    plddt_gate: float = STRUCTURE_PLDDT_GATE,
    hbond_max: float = TRIAD_HBOND_MAX_ANGSTROM,
) -> dict[str, object]:
    triad = find_catalytic_triad(prediction.sequence, prediction.residues, hbond_max=hbond_max)
    plddt_pass = prediction.mean_plddt >= plddt_gate
    structural_gate_pass = bool(plddt_pass and triad.passes)
    result: dict[str, object] = {
        "sequence_length": len(prediction.sequence),
        "backend": prediction.backend,
        "mean_plddt": round(prediction.mean_plddt, 2),
        "plddt_gate": plddt_gate,
        "plddt_pass": plddt_pass,
        "triad": triad.as_dict(),
        "triad_hbond_max": hbond_max,
        "structural_gate_pass": structural_gate_pass,
    }
    calibration = load_structure_calibration(prediction.backend)
    if calibration is not None:
        result["grade"] = structural_grade(
            mean_plddt=prediction.mean_plddt,
            ser_his_distance=triad.ser_his_distance,
            his_asp_distance=triad.his_asp_distance,
            calibration=calibration,
        )
        result["grade"]["natural_n"] = calibration["count"]
    return result


class EsmAtlasBackend:
    """Fold via the public ESMAtlas ESMFold API (no local weights)."""

    name = "esmatlas"

    def __init__(self, *, url: str | None = None, timeout_seconds: int = 180) -> None:
        self.url = url or os.environ.get("ESMATLAS_FOLD_URL", "https://api.esmatlas.com/foldSequence/v1/pdb/")
        self.timeout_seconds = timeout_seconds

    def fold(self, sequence: str) -> str:
        import urllib.request

        request = urllib.request.Request(self.url, data=sequence.encode("utf-8"), method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8")


class EsmFoldLocalBackend:
    """Fold locally with transformers EsmForProteinFolding (facebook/esmfold_v1)."""

    name = "esmfold"

    def __init__(self, *, model_name: str | None = None, device: str | None = None) -> None:
        self.model_name = model_name or os.environ.get("ESMFOLD_MODEL_NAME", "facebook/esmfold_v1")
        self.device = device or os.environ.get("ESMFOLD_DEVICE", "")
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        import torch
        from transformers import AutoTokenizer, EsmForProteinFolding

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        model = EsmForProteinFolding.from_pretrained(self.model_name)
        if self.device:
            device = torch.device(self.device)
        elif torch.cuda.is_available():
            device = torch.device("cuda")
        else:
            device = torch.device("cpu")  # ESMFold's folding trunk is unreliable on MPS
        model = model.to(device)
        model.eval()
        self._device = device
        self._torch = torch
        self._model = model
        return model

    def fold(self, sequence: str) -> str:
        model = self._load()
        with self._torch.inference_mode():
            return model.infer_pdb(sequence)


def get_backend(name: str | None = None) -> FoldingBackend:
    resolved = (name or os.environ.get("STRUCTURE_GATE_BACKEND", "esmfold")).strip().lower()
    if resolved == "esmatlas":
        return EsmAtlasBackend()
    if resolved == "esmfold":
        return EsmFoldLocalBackend()
    raise ValueError(f"Unknown structure-gate backend: {resolved!r} (expected 'esmfold' or 'esmatlas')")


def fold_and_gate(
    sequence: str,
    *,
    backend: FoldingBackend | None = None,
    plddt_gate: float = STRUCTURE_PLDDT_GATE,
    hbond_max: float = TRIAD_HBOND_MAX_ANGSTROM,
) -> dict[str, object]:
    """Fold ``sequence`` and return the structural gate decision (pLDDT + real triad geometry)."""
    backend = backend or get_backend()
    pdb_text = backend.fold(sequence)
    residues, mean_plddt = parse_pdb(pdb_text)
    prediction = StructurePrediction(
        sequence=sequence,
        residues=residues,
        mean_plddt=mean_plddt,
        backend=backend.name,
        pdb_text=pdb_text,
    )
    result = gate_prediction(prediction, plddt_gate=plddt_gate, hbond_max=hbond_max)
    return result
