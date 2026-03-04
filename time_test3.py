import time
seq1 = "M" * 40 + "S" * 60 + "A" * 50 + "C" * 50 + "T" * 50 + "D" * 50
seq2 = "M" * 38 + "S" * 62 + "A" * 55 + "E" * 45 + "T" * 50 + "D" * 50

def levenshtein_old(left: str, right: str) -> int:
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
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]

def levenshtein_fast(left: str, right: str) -> int:
    if left == right: return 0
    if len(left) < len(right): left, right = right, left
    if not right: return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left):
        current = [i + 1]
        for j, right_char in enumerate(right):
            current.append(min(current[-1] + 1, previous[j + 1] + 1, previous[j] + (left_char != right_char)))
        previous = current
    return previous[-1]

t0 = time.time()
for _ in range(32):
    levenshtein_old(seq1, seq2)
t1 = time.time()
print("Levenshtein old:", t1 - t0)

t0 = time.time()
for _ in range(32):
    levenshtein_fast(seq1, seq2)
t1 = time.time()
print("Levenshtein fast:", t1 - t0)
