from tracefi import TraceFi
from tracefi.demo import run_demo

if __name__ == "__main__":
    with TraceFi() as trace:
        for trace_id in run_demo(trace):
            print(trace_id)
