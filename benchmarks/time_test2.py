import time
import difflib

seq1 = "M" * 40 + "S" * 60 + "A" * 50 + "C" * 50 + "T" * 50 + "D" * 50
seq2 = "M" * 40 + "S" * 60 + "A" * 50 + "C" * 50 + "T" * 50 + "D" * 50

# Test Levenshtein optimized
def levenshtein_fast(left: str, right: str) -> int:
    if left == right: return 0
    if len(left) < len(right): left, right = right, left
    if not right: return len(left)
    
    previous = range(len(right) + 1)
    for i, left_char in enumerate(left):
        current = [i + 1]
        for j, right_char in enumerate(right):
            current.append(min(current[-1] + 1, previous[j + 1] + 1, previous[j] + (left_char != right_char)))
        previous = current
    return previous[-1]

t0 = time.time()
for _ in range(32):
    levenshtein_fast(seq1, seq2)
t1 = time.time()
print("Levenshtein fast:", t1 - t0)

# Test difflib
t0 = time.time()
for _ in range(32):
    difflib.SequenceMatcher(None, seq1, seq2).ratio()
t1 = time.time()
print("Difflib ratio:", t1 - t0)
