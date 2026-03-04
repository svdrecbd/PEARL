import time
import heapq
import random

data = [(random.random(), {"id": i}) for i in range(12000)]

t0 = time.time()
for _ in range(100):
    sorted_data = sorted(data, key=lambda item: item[0], reverse=True)[:32]
t1 = time.time()
print("Sorted:", t1 - t0)

t0 = time.time()
for _ in range(100):
    heap_data = heapq.nlargest(32, data, key=lambda item: item[0])
t1 = time.time()
print("Heapq:", t1 - t0)
