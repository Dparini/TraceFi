from agenttrace import AgentTrace
from agenttrace.demo import run_demo

if __name__ == "__main__":
    with AgentTrace() as trace:
        for trace_id in run_demo(trace):
            print(trace_id)
