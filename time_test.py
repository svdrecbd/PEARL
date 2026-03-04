import time
from collections import Counter
import math

seq = "M" * 50 + "S" * 50 + "A" * 50 + "G" * 50 + "T" * 50 + "D" * 50

# Test tandem repeat
t0 = time.time()
for _ in range(100):
    best_similarity = 0.0
    for block_size in range(16, 25, 4):
        max_start = len(seq) - (2 * block_size)
        for start in range(max_start + 1):
            left = seq[start : start + block_size]
            for gap in range(7):
                right_start = start + block_size + gap
                if right_start + block_size > len(seq):
                    break
                right = seq[right_start : right_start + block_size]
                matches = sum(left_char == right_char for left_char, right_char in zip(left, right))
                best_similarity = max(best_similarity, matches / block_size)
t1 = time.time()
print("Tandem repeat:", t1 - t0)

# Test local entropy
def compute_shannon_entropy(sequence: str) -> float:
    counts = Counter(sequence)
    length = len(sequence)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())

t0 = time.time()
for _ in range(100):
    window_size = 20
    min_entropy = math.inf
    for start in range(len(seq) - window_size + 1):
        window = seq[start : start + window_size]
        min_entropy = min(min_entropy, compute_shannon_entropy(window))
t1 = time.time()
print("Local entropy:", t1 - t0)

# Test Levenshtein
def levenshtein(left: str, right: str) -> int:
    if left == right: return 0
    if not left: return len(right)
    if not right: return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (left_char != right_char)
            current.append(insert_cost if insert_cost < delete_cost and insert_cost < replace_cost else (delete_cost if delete_cost < replace_cost else replace_cost))
        previous = current
    return previous[-1]

seq2 = "M" * 40 + "S" * 60 + "A" * 50 + "C" * 50 + "T" * 50 + "D" * 50
t0 = time.time()
for _ in range(32): # typical shortlist size
    levenshtein(seq, seq2)
t1 = time.time()
print("Levenshtein:", t1 - t0)
